"""GET /events/{id}/history — price history behind the detail sparklines.

A separate endpoint on purpose: history is only wanted when one event is opened,
and inlining it into /divergences would grow that response without bound as
snapshots accumulate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from arbitrium.api.main import event_history
from arbitrium.db.models import Event, OddsSnapshot

UTC = timezone.utc


def _event_with_history(db_session, points):
    ev = Event(
        sport="nfl", league="NFL", home_team="Kansas City Chiefs",
        away_team="Denver Broncos",
        scheduled_start=datetime.now(UTC) + timedelta(days=500), status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    base = datetime.now(UTC) - timedelta(hours=len(points))
    for i, (source, team, prob) in enumerate(points):
        db_session.add(OddsSnapshot(
            event_id=ev.id, source=source, outcome="home", team=team,
            implied_probability=prob, price_format="probability",
            snapshot_time=base + timedelta(hours=i), ingested_at=base + timedelta(hours=i),
        ))
    db_session.flush()
    return ev


def test_history_groups_by_source_and_team(db_session):
    ev = _event_with_history(db_session, [
        ("kalshi", "Kansas City Chiefs", 0.60),
        ("kalshi", "Kansas City Chiefs", 0.62),
        ("consensus", "Kansas City Chiefs", 0.58),
    ])
    out = event_history(ev.id, limit=400, db=db_session)
    by = {(s["source"], s["team"]): s for s in out["series"]}
    assert len(by[("kalshi", "Kansas City Chiefs")]["points"]) == 2
    assert len(by[("consensus", "Kansas City Chiefs")]["points"]) == 1
    assert out["total_points"] == 3


def test_points_are_chronological(db_session):
    ev = _event_with_history(db_session, [
        ("kalshi", "Kansas City Chiefs", 0.60),
        ("kalshi", "Kansas City Chiefs", 0.65),
        ("kalshi", "Kansas City Chiefs", 0.63),
    ])
    pts = event_history(ev.id, limit=400, db=db_session)["series"][0]["points"]
    assert [p["p"] for p in pts] == [0.60, 0.65, 0.63]
    assert [p["t"] for p in pts] == sorted(p["t"] for p in pts)


def test_event_with_no_history_returns_empty_not_error(db_session):
    """A brand-new event has no snapshots yet — that is a state, not a failure."""
    ev = _event_with_history(db_session, [])
    out = event_history(ev.id, limit=400, db=db_session)
    assert out["series"] == []
    assert out["total_points"] == 0


def test_unknown_event_404s(db_session):
    with pytest.raises(HTTPException) as exc:
        event_history(uuid.uuid4(), limit=400, db=db_session)
    assert exc.value.status_code == 404
