"""create odds_snapshots (append-only) + dedup trigger

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE odds_snapshots (
            id                   BIGSERIAL   PRIMARY KEY,
            event_id             UUID        NOT NULL REFERENCES events(id),
            source               TEXT        NOT NULL,
            outcome              TEXT        NOT NULL,
            implied_probability  NUMERIC(6,4) NOT NULL,
            raw_price            NUMERIC(8,4),
            price_format         TEXT        NOT NULL,
            liquidity_score      NUMERIC(8,2),
            order_book_depth     JSONB,
            ingested_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            snapshot_time        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_snapshots_event_source "
        "ON odds_snapshots (event_id, source, snapshot_time DESC);"
    )
    op.execute("CREATE INDEX idx_snapshots_snapshot_time ON odds_snapshots (snapshot_time DESC);")
    op.execute("CREATE INDEX idx_snapshots_source ON odds_snapshots (source);")

    # Dedup guard: skip an insert whose implied_probability is identical to the
    # most recent observation for the same (event_id, source, outcome). This is
    # change-data-capture semantics — NOT a global unique constraint — so a price
    # that returns to a prior value after moving IS recorded again (required for
    # honest CLV / calibration history). Dedup on price only for Phase 1.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION skip_unchanged_snapshot() RETURNS trigger AS $$
        DECLARE
            last_prob NUMERIC(6,4);
        BEGIN
            SELECT implied_probability INTO last_prob
            FROM odds_snapshots
            WHERE event_id = NEW.event_id
              AND source   = NEW.source
              AND outcome  = NEW.outcome
            ORDER BY snapshot_time DESC
            LIMIT 1;

            IF last_prob IS NOT NULL AND last_prob = NEW.implied_probability THEN
                RETURN NULL;  -- suppress this row, no error raised
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skip_unchanged_snapshot
            BEFORE INSERT ON odds_snapshots
            FOR EACH ROW EXECUTE FUNCTION skip_unchanged_snapshot();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_skip_unchanged_snapshot ON odds_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS skip_unchanged_snapshot();")
    op.execute("DROP TABLE IF EXISTS odds_snapshots CASCADE;")
