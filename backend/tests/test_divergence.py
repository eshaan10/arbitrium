"""Divergence scoring: status rules, team-anchored joins, and what is NOT scored.

The pure tests pin the honesty rules (thin consensus and single-source events are
labelled, never silently dropped, and never assigned a number). The DB test proves
the join survives an authoritative home/away flip, which is the whole reason
``odds_snapshots.team`` exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketedge.db.models import Event, OddsSnapshot
from marketedge.divergence.engine import (
    DivergenceStatus,
    OutcomeQuote,
    compute_divergences,
    score_event,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 14, 17, 0, tzinfo=UTC)


def _q(team, prob, *, n_books=None, outcome="home"):
    return OutcomeQuote(
        outcome=outcome, team=team, implied_probability=prob,
        snapshot_time=T0, n_books=n_books,
    )


def _pair(kalshi_home, kalshi_away, cons_home, cons_away, n_books):
    kalshi = [_q("Chiefs", kalshi_home), _q("Broncos", kalshi_away, outcome="away")]
    consensus = [
        _q("Chiefs", cons_home, n_books=n_books),
        _q("Broncos", cons_away, n_books=n_books, outcome="away"),
    ]
    return kalshi, consensus


# --- scored path -------------------------------------------------------------


def test_scored_when_both_sources_and_enough_books():
    k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    status, _, n_books, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=c)
    assert status is DivergenceStatus.SCORED
    assert n_books == 5
    by_team = {r.team: r for r in rows}
    # Sign convention: positive => Kalshi prices that team HIGHER than the books.
    assert by_team["Chiefs"].divergence == 0.60 - 0.55
    assert by_team["Broncos"].divergence == 0.40 - 0.45
    assert abs(max_abs - 0.05) < 1e-9


def test_book_count_uses_the_weaker_side():
    k, _ = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    consensus = [_q("Chiefs", 0.55, n_books=9), _q("Broncos", 0.45, n_books=2, outcome="away")]
    status, _, n_books, _, _ = score_event(kalshi_quotes=k, consensus_quotes=consensus)
    assert n_books == 2
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS


# --- the honesty rules -------------------------------------------------------


def test_thin_consensus_is_flagged_and_carries_no_number():
    k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=1)
    status, reason, n_books, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=c)
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS
    assert n_books == 1
    assert max_abs is None
    # Observed prices survive (they are real observations); the SCORE does not.
    assert all(r.divergence is None for r in rows)
    assert all(r.kalshi_probability is not None for r in rows)
    assert all(r.consensus_probability is not None for r in rows)
    assert "1 bookmaker" in reason


def test_book_floor_is_a_hard_boundary():
    for n, expected in ((2, DivergenceStatus.INSUFFICIENT_CONSENSUS),
                        (3, DivergenceStatus.SCORED)):
        k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=n)
        status, _, _, _, _ = score_event(kalshi_quotes=k, consensus_quotes=c, min_books=3)
        assert status is expected, f"n_books={n}"


def test_single_source_is_labelled_not_dropped():
    k, _ = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    status, reason, _, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=[])
    assert status is DivergenceStatus.SINGLE_SOURCE
    assert max_abs is None
    assert "kalshi" in reason
    # The event still reports what it DOES know.
    assert {r.team for r in rows} == {"Chiefs", "Broncos"}
    assert all(r.consensus_probability is None for r in rows)


def test_mismatched_outcome_keys_are_flagged_not_scored():
    kalshi = [_q("Chiefs", 0.60), _q("Broncos", 0.40, outcome="away")]
    consensus = [_q("Chiefs", 0.55, n_books=9), _q("Raiders", 0.45, n_books=9, outcome="away")]
    status, _, _, _, max_abs = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.INCOMPARABLE
    assert max_abs is None


def test_draw_outcomes_join_on_outcome_when_team_is_null():
    kalshi = [_q(None, 0.25, outcome="draw")]
    consensus = [_q(None, 0.20, n_books=6, outcome="draw")]
    status, _, _, rows, max_abs = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.SCORED
    assert rows[0].join_key == "__draw__"
    assert abs(max_abs - 0.05) < 1e-9


# --- DB: the join must survive a home/away flip ------------------------------


def _mk_snapshot(event_id, source, outcome, team, prob, **kw):
    return OddsSnapshot(
        event_id=event_id, source=source, outcome=outcome, team=team,
        implied_probability=prob, price_format="probability",
        snapshot_time=T0, ingested_at=T0, **kw,
    )


def test_divergence_joins_on_team_not_home_away(db_session):
    """Kalshi wrote 'home'=Chiefs; Odds API later proves Chiefs were AWAY.

    The append-only Kalshi row still says outcome='home'. If the comparison keyed
    on home/away it would now compare Chiefs against Broncos. Keyed on team, it
    stays correct.
    """
    start = datetime.now(UTC) + timedelta(days=400)
    ev = Event(
        sport="nfl", league="NFL", home_team="Kansas City Chiefs",
        away_team="Denver Broncos", scheduled_start=start, status="scheduled",
        home_away_source="kalshi_provisional",
    )
    db_session.add(ev)
    db_session.flush()

    db_session.add(_mk_snapshot(ev.id, "kalshi", "home", "Kansas City Chiefs", 0.62))
    db_session.add(_mk_snapshot(ev.id, "kalshi", "away", "Denver Broncos", 0.38))
    db_session.flush()

    # Authoritative flip: the Odds API says Denver is home.
    ev.home_team, ev.away_team = "Denver Broncos", "Kansas City Chiefs"
    ev.home_away_source = "odds_api"
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "home", "Denver Broncos", 0.40,
        order_book_depth={"n_books": 6},
    ))
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "away", "Kansas City Chiefs", 0.60,
        order_book_depth={"n_books": 6},
    ))
    db_session.flush()

    results = compute_divergences(db_session, sport="nfl")
    mine = [r for r in results if r.event_id == ev.id]
    assert len(mine) == 1
    row = mine[0]
    assert row.status is DivergenceStatus.SCORED
    by_team = {o.team: o for o in row.outcomes}
    # Chiefs: kalshi 0.62 vs consensus 0.60 — NOT 0.62 vs 0.40.
    assert abs(by_team["Kansas City Chiefs"].divergence - 0.02) < 1e-9
    assert abs(by_team["Denver Broncos"].divergence - (-0.02)) < 1e-9


def test_latest_snapshot_wins(db_session):
    start = datetime.now(UTC) + timedelta(days=401)
    ev = Event(
        sport="nfl", league="NFL", home_team="Buffalo Bills",
        away_team="Miami Dolphins", scheduled_start=start, status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    for prob, t in ((0.50, T0), (0.70, T0 + timedelta(hours=1))):
        db_session.add(OddsSnapshot(
            event_id=ev.id, source="kalshi", outcome="home", team="Buffalo Bills",
            implied_probability=prob, price_format="probability",
            snapshot_time=t, ingested_at=t,
        ))
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "home", "Buffalo Bills", 0.60,
        order_book_depth={"n_books": 4},
    ))
    db_session.flush()

    row = [r for r in compute_divergences(db_session, sport="nfl") if r.event_id == ev.id][0]
    bills = {o.team: o for o in row.outcomes}["Buffalo Bills"]
    assert bills.kalshi_probability == 0.70  # not the stale 0.50
