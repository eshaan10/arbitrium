"""Snapshot insertion that survives the dedup trigger.

``odds_snapshots`` has a BEFORE INSERT trigger that returns NULL for a row whose
price is unchanged since the last observation (migration 0002). Postgres then
silently inserts nothing for that row — which is exactly what we want.

What we cannot use is the ORM unit of work. ``session.add()`` + flush emits
INSERT ... RETURNING id (the PK is server-generated), and SQLAlchemy checks that
it gets back one row per row sent. The trigger returns fewer, so SQLAlchemy raises

    FlushError: Multi-row INSERT statement ... did not produce the correct number
    of INSERTed rows for RETURNING

and aborts the WHOLE flush — losing the genuinely-changed rows alongside the
suppressed ones. That is how a working dedup trigger silently took the entire
ingest pipeline down: every poll after the first raised, so no new price history
accumulated at all.

Core executemany has no RETURNING clause and no such row-count expectation, so
suppression stays invisible to the client, as designed.
"""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from marketedge.db.models import OddsSnapshot


def snapshot_count(session: Session) -> int:
    """Total rows in ``odds_snapshots``, for measuring what a pass actually wrote."""
    return session.execute(select(func.count()).select_from(OddsSnapshot)).scalar() or 0


def insert_snapshots(session: Session, rows: list[dict]) -> int:
    """Append snapshot rows, letting the dedup trigger drop unchanged prices.

    Returns rows ATTEMPTED, not rows persisted — the trigger decides the latter
    and deliberately does not tell us. Use :func:`snapshot_count` around a whole
    pass to learn what was actually written; doing it per-call would add a COUNT
    query per event for no benefit.
    """
    if not rows:
        return 0
    session.execute(insert(OddsSnapshot), rows)
    return len(rows)
