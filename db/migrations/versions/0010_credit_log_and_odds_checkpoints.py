"""add credit_log + odds_checkpoints (both append-only)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10

CREDIT_LOG records every Odds API response: which sport, what it cost (the
``x-requests-last`` header) and what was left (``x-requests-remaining``). Before
this the balance lived only on an in-memory client, so a restart forgot it and
the governor would have had nothing durable to pace a month against. Free calls
(/events) are logged too, at 0 credits: their headers carry the real balance,
so the governor can learn it without spending anything.

ODDS_CHECKPOINTS records each game-clock checkpoint (t24h, t6h, t1h, close) as
captured or deliberately skipped for budget. It is the plan's memory — a
restarted scheduler re-plans from it rather than re-spending a checkpoint — and
the 'close' row tags the closing-line pass for CLV. The tag cannot live on
``odds_snapshots``: the dedup trigger drops an unchanged price, so a tagged row
could simply never be written.

Both tables are append-only and enforce it: UPDATE and DELETE raise. A ledger
that can be edited stops being evidence of what was spent.

NUMBERING: the NBA branch is expected to add a migration too. If it lands first
as 0010, renumber this one to 0011 with ``down_revision`` pointing at it; the two
touch disjoint tables, so order does not matter.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE credit_log (
            id               BIGSERIAL   PRIMARY KEY,
            called_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sport            TEXT,
            sport_key        TEXT        NOT NULL,
            endpoint         TEXT        NOT NULL
                CHECK (endpoint IN ('odds', 'scores', 'events')),
            checkpoint       TEXT,
            credits_used     INT         NOT NULL CHECK (credits_used >= 0),
            remaining        INT,
            used             INT,
            events_returned  INT
        );
        """
    )
    # The governor reads "latest balance" and "spent since midnight" every pass.
    op.execute("CREATE INDEX idx_credit_log_called_at ON credit_log (called_at DESC);")

    op.execute(
        """
        CREATE TABLE odds_checkpoints (
            id           BIGSERIAL   PRIMARY KEY,
            event_id     UUID        NOT NULL REFERENCES events (id),
            sport        TEXT        NOT NULL,
            checkpoint   TEXT        NOT NULL
                CHECK (checkpoint IN ('t24h', 't6h', 't1h', 'close')),
            status       TEXT        NOT NULL
                CHECK (status IN ('captured', 'skipped_budget')),
            reason       TEXT,
            captured_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_odds_checkpoints_event ON odds_checkpoints (event_id, checkpoint);"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("credit_log", "odds_checkpoints"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS odds_checkpoints CASCADE;")
    op.execute("DROP TABLE IF EXISTS credit_log CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_mutation();")
