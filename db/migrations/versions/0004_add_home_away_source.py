"""add events.home_away_source (provisional vs authoritative home/away tracking)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-16

Kalshi does not label home vs away, so Kalshi-created events carry a PROVISIONAL
assignment ('kalshi_provisional'). Phase 2 matches each event to The Odds API
(which labels home/away explicitly) and upgrades the value to 'odds_api'. This
column makes that provisional/authoritative distinction explicit and queryable,
in keeping with the project's "never hide uncertainty" principle.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN home_away_source TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS home_away_source;")
