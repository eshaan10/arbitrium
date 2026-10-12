"""event_live_state: one row per event, upserted by the ESPN live-scores poller

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11

Why upsert (not append-only): a live scoreboard produces hundreds of mutations
per game and the UI reads the LATEST state only. An append-only table would
force every reader to re-aggregate a lookup that already has a natural key
(the event). Historical movement is not needed here; prices are the thing we
preserve the history of, scores are a derived fact of the world that only has
one value at a time.

Trigger: ``set_updated_at`` is created by migration 0001 and reused. The column
default on insert plus the trigger on update keeps ``updated_at`` honest from
both directions.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event_live_state (
            event_id         UUID        PRIMARY KEY
                REFERENCES events (id) ON DELETE CASCADE,
            status           TEXT        NOT NULL
                CHECK (status IN ('scheduled','in_progress','halftime','final','postponed')),
            period           INT,
            clock            TEXT,
            detail           TEXT,
            home_score       INT,
            away_score       INT,
            home_record      TEXT,
            away_record      TEXT,
            venue            TEXT,
            broadcast        TEXT,
            possession_side  TEXT        CHECK (possession_side IN ('home','away')),
            down_distance    TEXT,
            last_play        TEXT,
            linescore        JSONB,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_event_live_state_status ON event_live_state (status);"
    )
    op.execute(
        """
        CREATE TRIGGER trg_event_live_state_set_updated_at
            BEFORE UPDATE ON event_live_state
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_event_live_state_set_updated_at ON event_live_state;"
    )
    op.execute("DROP TABLE IF EXISTS event_live_state CASCADE;")
