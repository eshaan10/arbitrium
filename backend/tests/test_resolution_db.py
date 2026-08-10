"""Outcome resolution against a real database.

The centrepiece is ``test_winner_survives_a_home_away_flip``: it is the reason
results are stored as a canonical team name rather than 'home'/'away', and it is
literally unwritable under the old encoding.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from marketedge.config import settings
from marketedge.db.models import Event
from marketedge.ingestion.resolution import (
    CONFLICT_MARKER,
    DATA_LOST_MARKER,
    ResolutionOutcome,
    ScoreExtract,
    mark_unresolvable,
    pending_resolution,
    resolve_event,
    sport_keys_for,
)

UTC = timezone.utc


def _event(db_session, *, days, home="Kansas City Chiefs", away="Denver Broncos",
           odds_id=None, status="scheduled"):
    ev = Event(
        sport="nfl", league="NFL", home_team=home, away_team=away,
        scheduled_start=datetime.now(UTC) + timedelta(days=days),
        status=status, odds_api_event_id=odds_id,
    )
    db_session.add(ev)
    db_session.flush()
    return ev


def _extract(ev, home_score, away_score, *, odds_id=None):
    from marketedge.ingestion.resolution import decide_winner
    return ScoreExtract(
        odds_api_event_id=odds_id or ev.odds_api_event_id or "x",
        home_team=ev.home_team, away_team=ev.away_team,
        home_score=home_score, away_score=away_score,
        winner_team=decide_winner(ev.home_team, ev.away_team, home_score, away_score),
        commence_time=ev.scheduled_start, sport="nfl",
    )


# --- the write ---------------------------------------------------------------


def test_resolves_via_odds_api_event_id(db_session):
    ev = _event(db_session, days=-1, odds_id="odds-res-1")
    assert resolve_event(db_session, _extract(ev, 24, 17)) is ResolutionOutcome.RESOLVED
    db_session.flush()
    db_session.refresh(ev)
    assert (ev.home_score, ev.away_score) == (24, 17)
    assert ev.winner_team == "Kansas City Chiefs"
    assert ev.status == "final"
    assert ev.resolved_at is not None
    assert ev.resolution_source == "odds_api_scores"


def test_winner_side_is_generated_from_winner_team(db_session):
    ev = _event(db_session, days=-1, odds_id="odds-res-2")
    resolve_event(db_session, _extract(ev, 24, 17))
    db_session.flush()
    db_session.refresh(ev)
    assert ev.winner_side == "home"


def test_winner_survives_a_home_away_flip(db_session):
    """THE test this whole encoding exists for.

    Resolve, then apply the authoritative home/away correction that Phase 2's
    Odds API enrichment performs. The real-world winner must not move, and the
    relative label must follow the flip automatically.
    """
    ev = _event(db_session, days=-1, odds_id="odds-res-3")
    resolve_event(db_session, _extract(ev, 24, 17))  # Chiefs (home) win
    db_session.flush()
    db_session.refresh(ev)
    assert ev.winner_team == "Kansas City Chiefs"
    assert ev.winner_side == "home"

    # The Odds API says Denver was actually home.
    ev.home_team, ev.away_team = "Denver Broncos", "Kansas City Chiefs"
    ev.home_away_source = "odds_api"
    db_session.flush()
    db_session.refresh(ev)

    assert ev.winner_team == "Kansas City Chiefs"  # unchanged: still the real winner
    assert ev.winner_side == "away"  # recomputed by Postgres, no app code involved


def test_draw_is_distinguishable_from_unresolved(db_session):
    resolved = _event(db_session, days=-1, odds_id="odds-res-4")
    resolve_event(db_session, _extract(resolved, 20, 20))
    unresolved = _event(db_session, days=-1, odds_id="odds-res-5")
    db_session.flush()
    db_session.refresh(resolved)
    db_session.refresh(unresolved)

    assert resolved.winner_team is None and resolved.winner_side == "draw"
    assert unresolved.winner_team is None and unresolved.winner_side is None


# --- idempotency and conflict ------------------------------------------------


def test_re_running_is_a_silent_no_op(db_session):
    ev = _event(db_session, days=-1, odds_id="odds-res-6")
    resolve_event(db_session, _extract(ev, 24, 17))
    db_session.flush()
    db_session.refresh(ev)
    first_resolved_at = ev.resolved_at

    assert resolve_event(db_session, _extract(ev, 24, 17)) is ResolutionOutcome.UNCHANGED
    db_session.flush()
    db_session.refresh(ev)
    assert ev.resolved_at == first_resolved_at  # not re-stamped


def test_conflicting_result_is_logged_and_not_applied(db_session, caplog):
    ev = _event(db_session, days=-1, odds_id="odds-res-7")
    resolve_event(db_session, _extract(ev, 24, 17))
    db_session.flush()

    with caplog.at_level(logging.ERROR):
        outcome = resolve_event(db_session, _extract(ev, 21, 17))
    db_session.flush()
    db_session.refresh(ev)

    assert outcome is ResolutionOutcome.CONFLICT
    assert (ev.home_score, ev.away_score) == (24, 17)  # untouched
    assert CONFLICT_MARKER in caplog.text


def test_unknown_event_is_not_found(db_session):
    """The scores endpoint returns games we never ingested."""
    extract = ScoreExtract(
        odds_api_event_id="never-seen", home_team="Kansas City Chiefs",
        away_team="Denver Broncos", home_score=24, away_score=17,
        winner_team="Kansas City Chiefs",
        commence_time=datetime.now(UTC) + timedelta(days=900), sport="nfl",
    )
    assert resolve_event(db_session, extract) is ResolutionOutcome.NOT_FOUND


def test_kalshi_only_event_resolves_via_the_matcher(db_session):
    """No odds id, so the fast path misses — the shared matcher must catch it.

    Without this, every single-source event would be permanently ungradeable.
    """
    ev = _event(db_session, days=-1, home="Buffalo Bills", away="Miami Dolphins")
    assert ev.odds_api_event_id is None
    assert resolve_event(db_session, _extract(ev, 30, 27, odds_id="odds-res-8")) is (
        ResolutionOutcome.RESOLVED
    )
    db_session.flush()
    db_session.refresh(ev)
    assert ev.winner_team == "Buffalo Bills"


# --- constraints -------------------------------------------------------------


def test_winner_must_be_a_participant(db_session):
    """A winner naming neither side is rejected by the database itself.

    Run inside a SAVEPOINT: the violation aborts its own transaction, and without
    nesting that would tear down the fixture's outer transaction too.
    """
    ev = _event(db_session, days=-1, odds_id="odds-res-9")
    savepoint = db_session.begin_nested()
    # IntegrityError specifically — a blind `Exception` would also pass on a typo
    # in the SQL, proving nothing about the constraint.
    with pytest.raises(IntegrityError, match="ck_events_winner_is_a_participant"):
        db_session.execute(
            text("UPDATE events SET winner_team = 'Chicago Bears' WHERE id = :i"),
            {"i": str(ev.id)},
        )
        db_session.flush()
    savepoint.rollback()

    db_session.refresh(ev)
    assert ev.winner_team is None  # the bad write never landed


# --- the window --------------------------------------------------------------


def test_pending_excludes_games_too_recent_to_be_final(db_session):
    _event(db_session, days=0, odds_id="odds-res-10")  # kicks off now
    summary = pending_resolution(db_session)
    starts = [summary.oldest_pending_start]
    assert all(s is None or s < datetime.now(UTC) for s in starts)


def test_mark_unresolvable_condemns_only_past_window(db_session, caplog):
    hours = settings.resolution_unresolvable_after_hours
    doomed = _event(db_session, days=-(hours / 24) - 1, odds_id="odds-res-11")
    safe = _event(db_session, days=-0.5, odds_id="odds-res-12")
    db_session.flush()

    with caplog.at_level(logging.ERROR):
        n = mark_unresolvable(db_session)
    db_session.flush()
    db_session.refresh(doomed)
    db_session.refresh(safe)

    assert n >= 1
    assert doomed.status == "unresolvable"
    assert doomed.unresolvable_reason == "window_expired"
    assert safe.status == "scheduled"  # still has time
    assert DATA_LOST_MARKER in caplog.text


def test_hours_until_next_data_loss_counts_down(db_session):
    _event(db_session, days=-1, odds_id="odds-res-13")
    summary = pending_resolution(db_session)
    countdown = summary.hours_until_next_data_loss
    assert countdown is not None
    assert 0 < countdown < settings.resolution_unresolvable_after_hours


def test_sport_keys_cover_preseason_and_regular_season():
    keys = sport_keys_for(["nfl"])
    assert "americanfootball_nfl" in keys
    assert "americanfootball_nfl_preseason" in keys  # the gap Phase 2 left open


# --- the scheduled_start clobber ---------------------------------------------


def test_kalshi_upsert_does_not_clobber_an_authoritative_kickoff(db_session):
    """Regression: the Odds API's exact kickoff must survive the next Kalshi poll.

    Kalshi's start comes from the event ticker and is only a DATE, landing on
    midnight UTC while the real kickoff is an evening US time up to ~24h later.
    The upsert used to overwrite the enriched value every 5 minutes, which made
    the 84h resolution window fire up to a day early — that is how a real outcome
    was condemned before it had actually aged out.
    """
    from marketedge.ingestion.kalshi import KalshiEventMetadata, upsert_event

    authoritative = datetime.now(UTC) + timedelta(days=600, hours=23)
    placeholder = authoritative.replace(hour=0, minute=0, second=0, microsecond=0)

    ev = Event(
        sport="nfl", league="NFL", home_team="Arizona Cardinals",
        away_team="Carolina Panthers", scheduled_start=authoritative,
        status="scheduled", home_away_source="odds_api",
        kalshi_event_ticker="KXNFLGAME-99AUG06CARARI",
    )
    db_session.add(ev)
    db_session.flush()

    upsert_event(db_session, KalshiEventMetadata(
        kalshi_event_ticker="KXNFLGAME-99AUG06CARARI", sport="nfl", league="NFL",
        home_team="Carolina Panthers", away_team="Arizona Cardinals",
        scheduled_start=placeholder, outcome_markets={},
    ))
    db_session.flush()
    db_session.refresh(ev)

    assert ev.scheduled_start == authoritative, "the exact kickoff was clobbered"
    assert ev.home_team == "Arizona Cardinals"  # home/away still protected too


def test_kalshi_upsert_still_refreshes_a_provisional_kickoff(db_session):
    """Protection applies only once a source is authoritative — a still-provisional
    event must keep tracking Kalshi, since postponements really do move."""
    from marketedge.ingestion.kalshi import KalshiEventMetadata, upsert_event

    original = datetime.now(UTC) + timedelta(days=601)
    moved = original + timedelta(days=1)
    ev = Event(
        sport="nfl", league="NFL", home_team="Chicago Bears", away_team="Green Bay Packers",
        scheduled_start=original, status="scheduled",
        home_away_source="kalshi_provisional",
        kalshi_event_ticker="KXNFLGAME-99AUG07GBCHI",
    )
    db_session.add(ev)
    db_session.flush()

    upsert_event(db_session, KalshiEventMetadata(
        kalshi_event_ticker="KXNFLGAME-99AUG07GBCHI", sport="nfl", league="NFL",
        home_team="Chicago Bears", away_team="Green Bay Packers",
        scheduled_start=moved, outcome_markets={},
    ))
    db_session.flush()
    db_session.refresh(ev)
    assert ev.scheduled_start == moved
