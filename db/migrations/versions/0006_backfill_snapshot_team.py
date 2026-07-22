"""backfill odds_snapshots.team left NULL by the pre-fix Kalshi ingest

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-22

Migration 0005 added ``team`` and backfilled every row that existed at the time.
But the Kalshi ingest path itself was never updated to POPULATE the new column,
so every poll after 0005 kept appending rows with team = NULL. This backfills
those rows; the ingest fix (``ingest_event`` in ingestion/kalshi.py) is what stops
them from coming back.

This is not a rewrite of history: ``team`` is a derived label for an observation,
not the observation. The price, probability and timestamps are untouched.

Guard that 0005 did not need: 0005 ran before any authoritative home/away flip,
so reading the event's CURRENT home/away was guaranteed to reproduce what the row
was written under. That is no longer guaranteed in general, so we only backfill
rows whose event is still ``kalshi_provisional``. If an event has already been
flipped to 'odds_api', its current home/away may be the reverse of what the row
was written under and the team cannot be recovered from it — those rows are left
NULL deliberately rather than filled with a coin-flip. (At the time of writing
this migration all 33 events were still provisional, so no row is skipped.)
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE odds_snapshots s
        SET team = CASE
            WHEN s.outcome = 'home' THEN e.home_team
            WHEN s.outcome = 'away' THEN e.away_team
        END
        FROM events e
        WHERE e.id = s.event_id
          AND s.team IS NULL
          AND s.outcome IN ('home', 'away')
          AND e.home_away_source = 'kalshi_provisional';
        """
    )


def downgrade() -> None:
    # Intentionally a no-op: we cannot distinguish rows this migration filled from
    # rows 0005 filled, and blanking both would be worse than leaving them set.
    pass
