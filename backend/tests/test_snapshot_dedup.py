"""The dedup trigger must suppress rows WITHOUT breaking the insert.

Regression test for the bug that silently took ingestion down: the BEFORE INSERT
trigger returned NULL for unchanged prices, the ORM's INSERT...RETURNING got back
fewer rows than it sent, and SQLAlchemy raised FlushError — aborting the whole
flush, so genuinely-changed prices were lost too. Every poll after the first
failed, and no price history accumulated.

These tests hit the real trigger (they need a database), because that is exactly
the layer where a mirrored/mocked version would have kept passing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from arbitrium.db.models import Event, OddsSnapshot
from arbitrium.ingestion.snapshots import insert_snapshots

UTC = timezone.utc


def _event(db_session, offset_days):
    ev = Event(
        sport="nfl", league="NFL", home_team="Seattle Seahawks",
        away_team="Los Angeles Rams",
        scheduled_start=datetime.now(UTC) + timedelta(days=offset_days),
        status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    return ev


def _row(event_id, prob, t, outcome="home", team="Seattle Seahawks"):
    return {
        "event_id": event_id, "source": "kalshi", "outcome": outcome, "team": team,
        "implied_probability": prob, "price_format": "probability",
        "ingested_at": t, "snapshot_time": t,
    }


def _count(db_session, event_id):
    return db_session.execute(
        select(func.count()).select_from(OddsSnapshot).where(OddsSnapshot.event_id == event_id)
    ).scalar()


def test_unchanged_price_is_suppressed_without_raising(db_session):
    ev = _event(db_session, 430)
    t0 = datetime.now(UTC)

    insert_snapshots(db_session, [_row(ev.id, 0.55, t0)])
    db_session.flush()
    assert _count(db_session, ev.id) == 1

    # Same price again: the trigger drops it. This is the call that used to raise.
    insert_snapshots(db_session, [_row(ev.id, 0.55, t0 + timedelta(minutes=5))])
    db_session.flush()
    assert _count(db_session, ev.id) == 1, "unchanged price should not append a row"


def test_changed_price_still_appends(db_session):
    ev = _event(db_session, 431)
    t0 = datetime.now(UTC)
    insert_snapshots(db_session, [_row(ev.id, 0.55, t0)])
    db_session.flush()
    insert_snapshots(db_session, [_row(ev.id, 0.58, t0 + timedelta(minutes=5))])
    db_session.flush()
    assert _count(db_session, ev.id) == 2  # genuine oscillation is preserved


def test_partial_suppression_does_not_lose_the_changed_row(db_session):
    """The critical case: one row suppressed, one changed, in ONE insert.

    This is what a real poll looks like — one side of the book moved and the other
    didn't. The old ORM path lost BOTH rows here.
    """
    ev = _event(db_session, 432)
    t0 = datetime.now(UTC)
    insert_snapshots(db_session, [
        _row(ev.id, 0.55, t0, outcome="home", team="Seattle Seahawks"),
        _row(ev.id, 0.45, t0, outcome="away", team="Los Angeles Rams"),
    ])
    db_session.flush()
    assert _count(db_session, ev.id) == 2

    t1 = t0 + timedelta(minutes=5)
    attempted = insert_snapshots(db_session, [
        _row(ev.id, 0.55, t1, outcome="home", team="Seattle Seahawks"),  # unchanged
        _row(ev.id, 0.49, t1, outcome="away", team="Los Angeles Rams"),  # moved
    ])
    db_session.flush()

    assert attempted == 2  # the return value counts rows ATTEMPTED, not persisted
    assert _count(db_session, ev.id) == 3, "the changed row must survive"
    latest = db_session.execute(
        select(OddsSnapshot.implied_probability)
        .where(OddsSnapshot.event_id == ev.id, OddsSnapshot.outcome == "away")
        .order_by(OddsSnapshot.snapshot_time.desc())
        .limit(1)
    ).scalar()
    assert float(latest) == 0.49


def test_empty_insert_is_a_noop(db_session):
    assert insert_snapshots(db_session, []) == 0
