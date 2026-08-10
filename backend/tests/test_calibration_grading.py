"""Grading and closing-line value against a real database.

The properties that matter: reconstruction must never see a price that did not
exist yet, a game must count once rather than twice, and a re-run must not
inflate the sample the whole gate depends on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from marketedge.calibration import clv as clv_mod
from marketedge.calibration.grading import (
    ORIGIN_LIVE,
    ORIGIN_RECONSTRUCTED,
    backfill_reconstructions,
    confidence_band,
    grade_pending,
    reconstruct_first_call,
    record_prediction,
    source_reliability_pairs,
)
from marketedge.db.models import CalibrationHistory, Event, OddsSnapshot
from marketedge.ingestion.snapshots import insert_snapshots

UTC = timezone.utc


def _game(db, *, days_ago, home="Kansas City Chiefs", away="Denver Broncos",
          winner=None, status="final"):
    ev = Event(
        sport="nfl", league="NFL", home_team=home, away_team=away,
        scheduled_start=datetime.now(UTC) - timedelta(days=days_ago),
        status=status, winner_team=winner,
        home_score=24 if status == "final" else None,
        away_score=17 if status == "final" else None,
    )
    db.add(ev)
    db.flush()
    return ev


def _snap(db, ev, source, team, prob, *, minutes_before, depth=None):
    """Insert via the production Core path, not the ORM.

    The dedup trigger returns NULL for an unchanged price, which makes the ORM's
    INSERT...RETURNING raise — the same FlushError that once silently killed
    ingestion. Tests must write the way production does or they exercise a path
    that does not exist.
    """
    at = ev.scheduled_start - timedelta(minutes=minutes_before)
    insert_snapshots(db, [{
        "event_id": ev.id, "source": source,
        # Distinct outcome per team: the dedup trigger keys on
        # (event_id, source, outcome), so reusing 'home' for both sides would
        # make one team's price suppress the other's.
        "outcome": "home" if team == ev.home_team else "away",
        "team": team, "implied_probability": prob, "price_format": "probability",
        "snapshot_time": at, "ingested_at": at, "order_book_depth": depth,
    }])
    db.flush()


# --- source reliability ------------------------------------------------------


def test_one_observation_per_game_not_per_outcome(db_session):
    """Grading both sides would double a perfectly anti-correlated sample."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.60, minutes_before=120)
    _snap(db_session, ev, "kalshi", "Denver Broncos", 0.40, minutes_before=120)

    pairs = source_reliability_pairs(db_session, "kalshi")
    mine = [p for p in pairs if abs(p[0] - 0.60) < 1e-9 or abs(p[0] - 0.40) < 1e-9]
    assert len(mine) == 1, "the game was counted more than once"
    assert mine[0] == (0.60, True)  # home side, and the home team won


def test_a_source_that_never_priced_the_game_is_skipped(db_session):
    ev = _game(db_session, days_ago=2, winner="Buffalo Bills",
               home="Buffalo Bills", away="Miami Dolphins")
    _snap(db_session, ev, "kalshi", "Buffalo Bills", 0.55, minutes_before=90)
    consensus = source_reliability_pairs(db_session, "consensus")
    assert all(abs(p - 0.55) > 1e-9 for p, _ in consensus)


# --- closing-line value ------------------------------------------------------


def test_clv_is_positive_when_the_market_comes_to_a_yes_buy(db_session):
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.62, minutes_before=60)
    entry_at = ev.scheduled_start - timedelta(hours=6)

    obs = clv_mod.observe(db_session, ev, team="Kansas City Chiefs", side="yes",
                          entry_prob=0.55, entry_at=entry_at)
    assert obs is not None
    assert abs(obs.clv - 0.07) < 1e-9
    assert obs.beat_close


def test_clv_sign_flips_for_a_no_buy(db_session):
    """A No position gains when the Yes price FALLS."""
    ev = _game(db_session, days_ago=2, winner="Denver Broncos")
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.40, minutes_before=60)
    entry_at = ev.scheduled_start - timedelta(hours=6)

    obs = clv_mod.observe(db_session, ev, team="Kansas City Chiefs", side="no",
                          entry_prob=0.55, entry_at=entry_at)
    assert obs.clv > 0  # price fell 0.55 -> 0.40, which helps a No
    assert abs(obs.clv - 0.15) < 1e-9


def test_no_close_yields_none_not_zero(db_session):
    """A fabricated 0.0 would read as 'no edge' rather than 'not measurable'."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    obs = clv_mod.observe(db_session, ev, team="Kansas City Chiefs", side="yes",
                          entry_prob=0.55, entry_at=ev.scheduled_start - timedelta(hours=6))
    assert obs is None


def test_in_play_prices_are_not_treated_as_a_close(db_session):
    """A snapshot after kickoff may already reflect the result."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    db_session.add(OddsSnapshot(
        event_id=ev.id, source="kalshi", outcome="home", team="Kansas City Chiefs",
        implied_probability=0.97, price_format="probability",
        snapshot_time=ev.scheduled_start + timedelta(hours=1),
        ingested_at=ev.scheduled_start + timedelta(hours=1),
    ))
    db_session.flush()
    assert clv_mod.closing_price(
        db_session, ev.id, "Kansas City Chiefs", kickoff=ev.scheduled_start) is None


# --- reconstruction ----------------------------------------------------------


def test_reconstruction_never_sees_a_future_price(db_session):
    """The whole legitimacy of a backtest rests on this.

    NOTE the consensus price moves between the two snapshots. It has to: the
    dedup trigger keys on implied_probability alone, so an unchanged median with
    a CHANGED book count is suppressed and the new n_books never reaches the
    table. See the known-limitation note in marketedge/calibration/grading.py.
    """
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs", status="final")
    # Early: a thin consensus that must NOT produce a call.
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.50, minutes_before=600,
          depth={"yes_bid": 0.49, "yes_ask": 0.50, "yes_ask_size": 100})
    _snap(db_session, ev, "consensus", "Kansas City Chiefs", 0.70, minutes_before=600,
          depth={"n_books": 1})
    # Later: enough books, so the first legitimate call is here, not earlier.
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.52, minutes_before=300,
          depth={"yes_bid": 0.51, "yes_ask": 0.52, "yes_ask_size": 100})
    _snap(db_session, ev, "consensus", "Kansas City Chiefs", 0.71, minutes_before=300,
          depth={"n_books": 9})

    call = reconstruct_first_call(db_session, ev)
    assert call is not None
    assert call.at == ev.scheduled_start - timedelta(minutes=300)
    assert abs(call.entry_prob - 0.52) < 1e-9  # the price available AT that moment


def test_thin_consensus_produces_no_reconstructed_call(db_session):
    """The backtest applies the same book floor the live engine does."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.50, minutes_before=300,
          depth={"yes_bid": 0.49, "yes_ask": 0.50})
    _snap(db_session, ev, "consensus", "Kansas City Chiefs", 0.70, minutes_before=300,
          depth={"n_books": 1})
    assert reconstruct_first_call(db_session, ev) is None


# --- recording and grading ---------------------------------------------------


def _record(db, ev, *, origin, team="Kansas City Chiefs", prob=0.60):
    record_prediction(
        db, event_id=ev.id, subject_team=team, predicted_prob=prob,
        divergence_score=0.05, band="good", entry_prob=0.55,
        flagged_at=ev.scheduled_start - timedelta(hours=6), origin=origin,
    )
    db.flush()


def test_re_recording_updates_rather_than_duplicating(db_session):
    """Duplicates would silently inflate the sample the gate depends on."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _record(db_session, ev, origin=ORIGIN_RECONSTRUCTED)
    _record(db_session, ev, origin=ORIGIN_RECONSTRUCTED, prob=0.65)

    n = db_session.execute(
        select(func.count()).select_from(CalibrationHistory)
        .where(CalibrationHistory.event_id == ev.id)
    ).scalar()
    assert n == 1
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert float(row.predicted_prob) == 0.65


def test_live_and_reconstructed_coexist_as_separate_rows(db_session):
    """They are different kinds of evidence and must never be merged."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _record(db_session, ev, origin=ORIGIN_LIVE)
    _record(db_session, ev, origin=ORIGIN_RECONSTRUCTED)
    n = db_session.execute(
        select(func.count()).select_from(CalibrationHistory)
        .where(CalibrationHistory.event_id == ev.id)
    ).scalar()
    assert n == 2


def test_grading_marks_a_correct_call(db_session):
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _record(db_session, ev, origin=ORIGIN_LIVE, team="Kansas City Chiefs")
    grade_pending(db_session)
    db_session.flush()
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert row.outcome_correct is True
    assert row.graded_at is not None


def test_grading_marks_a_wrong_call(db_session):
    ev = _game(db_session, days_ago=2, winner="Denver Broncos")
    _record(db_session, ev, origin=ORIGIN_LIVE, team="Kansas City Chiefs")
    grade_pending(db_session)
    db_session.flush()
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert row.outcome_correct is False


def test_a_draw_is_left_ungraded_rather_than_scored_as_a_loss(db_session):
    """Neither correct nor incorrect for a 'team wins' call."""
    ev = _game(db_session, days_ago=2, winner=None)
    ev.home_score = ev.away_score = 20
    db_session.flush()
    _record(db_session, ev, origin=ORIGIN_LIVE)
    grade_pending(db_session)
    db_session.flush()
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert row.outcome_correct is None


def test_grading_uses_winner_team_not_home_away(db_session):
    """A later home/away re-label must not flip an already-graded result."""
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _record(db_session, ev, origin=ORIGIN_LIVE, team="Kansas City Chiefs")
    grade_pending(db_session)
    db_session.flush()

    ev.home_team, ev.away_team = "Denver Broncos", "Kansas City Chiefs"
    db_session.flush()
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert row.outcome_correct is True  # unchanged


def test_unresolved_games_are_not_graded(db_session):
    ev = _game(db_session, days_ago=2, status="scheduled")
    _record(db_session, ev, origin=ORIGIN_LIVE)
    grade_pending(db_session)
    db_session.flush()
    row = db_session.execute(
        select(CalibrationHistory).where(CalibrationHistory.event_id == ev.id)
    ).scalar_one()
    assert row.outcome_correct is None


# --- confidence bands --------------------------------------------------------


def test_band_reflects_books_and_depth_together():
    assert confidence_band(9, 1000) == "strong"
    assert confidence_band(9, 2) == "moderate"   # deep consensus, no size
    assert confidence_band(1, 1000) == "moderate"  # size, but no consensus
    assert confidence_band(1, 1) == "weak"


def test_backfill_is_idempotent(db_session):
    ev = _game(db_session, days_ago=2, winner="Kansas City Chiefs")
    _snap(db_session, ev, "kalshi", "Kansas City Chiefs", 0.50, minutes_before=300,
          depth={"yes_bid": 0.49, "yes_ask": 0.50, "yes_ask_size": 100})
    _snap(db_session, ev, "consensus", "Kansas City Chiefs", 0.70, minutes_before=300,
          depth={"n_books": 9})
    backfill_reconstructions(db_session)
    backfill_reconstructions(db_session)
    db_session.flush()
    n = db_session.execute(
        select(func.count()).select_from(CalibrationHistory)
        .where(CalibrationHistory.event_id == ev.id)
    ).scalar()
    assert n == 1
