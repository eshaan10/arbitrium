"""create events

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() is core in PG13+, but pgcrypto is harmless to ensure.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.execute(
        """
        CREATE TABLE events (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sport                TEXT        NOT NULL,
            league               TEXT        NOT NULL,
            home_team            TEXT        NOT NULL,
            away_team            TEXT        NOT NULL,
            scheduled_start      TIMESTAMPTZ NOT NULL,
            status               TEXT        NOT NULL DEFAULT 'scheduled',
            home_score           INT,
            away_score           INT,
            winner               TEXT,
            resolved_at          TIMESTAMPTZ,
            kalshi_event_ticker  TEXT UNIQUE,
            odds_api_event_id    TEXT UNIQUE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX idx_events_sport_status ON events (sport, status);")
    op.execute("CREATE INDEX idx_events_scheduled_start ON events (scheduled_start DESC);")
    op.execute("CREATE INDEX idx_events_kalshi_ticker ON events (kalshi_event_ticker);")
    op.execute("CREATE INDEX idx_events_odds_api_id ON events (odds_api_event_id);")

    # Keep updated_at honest on any mutation (e.g. resolution). Events are the one
    # table we intentionally mutate; snapshots remain append-only.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_events_set_updated_at
            BEFORE UPDATE ON events
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_events_set_updated_at ON events;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.execute("DROP TABLE IF EXISTS events CASCADE;")
