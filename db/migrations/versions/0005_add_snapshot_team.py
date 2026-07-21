"""add odds_snapshots.team (divergence join anchor) + backfill

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17

The divergence engine joins Kalshi vs sportsbook snapshots on TEAM identity, not
home/away — because home/away is provisional for Kalshi until Phase 2 confirms it
against The Odds API, and odds_snapshots is append-only (a later home/away flip
must never retroactively corrupt an already-written row's meaning). ``team`` is
always known correctly at write time for both sources, so it is the stable anchor.

Backfill runs NOW, before any authoritative home/away flip, so the existing rows'
team matches the provisional home/away they were written under. 'draw' rows have
team = NULL (matched via outcome instead).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE odds_snapshots ADD COLUMN team TEXT;")
    # Backfill from each event's CURRENT (still-provisional) home/away. Safe only
    # because no authoritative flip has happened yet.
    op.execute(
        """
        UPDATE odds_snapshots s
        SET team = CASE
            WHEN s.outcome = 'home' THEN e.home_team
            WHEN s.outcome = 'away' THEN e.away_team
            ELSE NULL
        END
        FROM events e
        WHERE e.id = s.event_id AND s.outcome IN ('home', 'away');
        """
    )
    op.execute("CREATE INDEX idx_snapshots_event_team ON odds_snapshots (event_id, team);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_snapshots_event_team;")
    op.execute("ALTER TABLE odds_snapshots DROP COLUMN IF EXISTS team;")
