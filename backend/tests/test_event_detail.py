"""GET /events/{id} — the endpoint a deep link resolves against.

Deep links used to resolve against /divergences, which scores ONLY scheduled
events. So a saved link 404'd the instant its game kicked off — precisely when
someone opens it to find out what happened, and it made the finished-games view
unreachable. These tests pin the two halves of the fix:

* a scheduled event still returns the full divergence body, so the detail page
  and the list row cannot describe the same game differently;
* a finished event returns NO divergence, no edge and no recommendation, and
  instead reports what was actually recorded. Re-scoring a game nobody can bet
  on would emit a confident-looking number for a trade that no longer exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from arbitrium.api.main import divergences, event_detail
from arbitrium.db.models import Event, OddsSnapshot

UTC = timezone.utc


def _snapshot(db_session, ev, source, team, prob, when, **extra):
    db_session.add(
        OddsSnapshot(
            event_id=ev.id,
            source=source,
            outcome="home" if team == ev.home_team else "away",
            team=team,
            implied_probability=prob,
            price_format="probability",
            snapshot_time=when,
            ingested_at=when,
            **extra,
        )
    )


def _priced_event(db_session, *, status="scheduled", start=None, **fields):
    """An event with both sources quoting each side."""
    start = start or datetime.now(UTC) + timedelta(days=400)
    ev = Event(
        sport="nfl",
        league="NFL",
        home_team="Kansas City Chiefs",
        away_team="Denver Broncos",
        scheduled_start=start,
        status=status,
        **fields,
    )
    db_session.add(ev)
    db_session.flush()

    t = start - timedelta(days=1)
    for source in ("kalshi", "consensus"):
        _snapshot(db_session, ev, source, "Kansas City Chiefs", 0.60, t)
        _snapshot(db_session, ev, source, "Denver Broncos", 0.40, t)
    db_session.flush()
    return ev


def test_scheduled_event_matches_its_list_row(db_session):
    """One serializer, so a deep link and the list can never disagree."""
    ev = _priced_event(db_session)

    detail = event_detail(ev.id, db=db_session)
    listed = next(
        d
        for d in divergences(
            sport=None,
            status=None,
            min_divergence=None,
            tradeable_only=False,
            limit=1000,
            db=db_session,
        )["divergences"]
        if d["event_id"] == str(ev.id)
    )

    assert detail["divergence"] == listed
    assert detail["event"]["status"] == "scheduled"
    # A live event has no closing line — it has not closed.
    assert detail["closing"] is None


def test_finished_event_resolves_instead_of_404ing(db_session):
    """The bug this endpoint exists for: a past game must still open."""
    start = datetime.now(UTC) - timedelta(days=2)
    ev = _priced_event(
        db_session,
        status="final",
        start=start,
        winner_team="Kansas City Chiefs",
        home_score=27,
        away_score=13,
    )

    out = event_detail(ev.id, db=db_session)

    assert out["event"]["winner_team"] == "Kansas City Chiefs"
    assert out["event"]["home_score"] == 27
    # The whole point: no stale edge, no stale recommendation.
    assert out["divergence"] is None
    assert {c["source"] for c in out["closing"]} == {"kalshi", "consensus"}


def test_closing_stops_at_kickoff(db_session):
    """Kalshi keeps trading after the whistle; that is not a closing line.

    A price set once the game is half over describes a market that already knows
    the score. Reporting it as what the market believed going in would silently
    flatter every closing-line comparison drawn from this endpoint.
    """
    start = datetime.now(UTC) - timedelta(days=2)
    ev = _priced_event(
        db_session, status="final", start=start, home_score=27, away_score=13,
        winner_team="Kansas City Chiefs",
    )

    _snapshot(
        db_session, ev, "kalshi", "Kansas City Chiefs", 0.97, start + timedelta(hours=2)
    )
    db_session.flush()

    closing = event_detail(ev.id, db=db_session)["closing"]
    kalshi_home = next(
        c for c in closing if c["source"] == "kalshi" and c["team"] == "Kansas City Chiefs"
    )
    assert kalshi_home["implied_probability"] == pytest.approx(0.60)


def test_finished_event_with_no_prices_reports_an_empty_closing_list(db_session):
    """No observation is a state, not an error — and never a fabricated one."""
    ev = Event(
        sport="nfl",
        league="NFL",
        home_team="Chicago Bears",
        away_team="Green Bay Packers",
        scheduled_start=datetime.now(UTC) - timedelta(days=3),
        status="final",
        winner_team="Green Bay Packers",
        home_score=17,
        away_score=24,
    )
    db_session.add(ev)
    db_session.flush()

    out = event_detail(ev.id, db=db_session)
    assert out["divergence"] is None
    assert out["closing"] == []


def test_unresolvable_event_still_resolves(db_session):
    """A game whose result was lost is still openable, and says so."""
    ev = _priced_event(
        db_session,
        status="unresolvable",
        start=datetime.now(UTC) - timedelta(days=10),
        unresolvable_reason="scores_window_expired",
    )
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["unresolvable_reason"] == "scores_window_expired"
    assert out["event"]["winner_team"] is None
    assert out["divergence"] is None


def test_unknown_event_404s(db_session):
    with pytest.raises(HTTPException) as exc:
        event_detail(uuid.uuid4(), db=db_session)
    assert exc.value.status_code == 404
