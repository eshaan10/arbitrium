"""add outcome resolution columns + ingest_runs job history

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-22

Phase 3 needs two things before calibration can start: a place to record who
actually won, and a durable record of whether the jobs that collect it are
running.

WINNER ENCODING. ``events.winner`` was declared in 0001 as 'home' | 'away' |
'draw' — a home/away-RELATIVE label. That is the same shape as the bug migration
0005 was written to prevent: home/away is provisional for Kalshi-sourced events
and is corrected later by The Odds API, so a stored ``winner='home'`` silently
changes meaning the moment the correction lands. 0005 solved it for snapshots by
storing the stable identity (``team``) and deriving the relative label; results
get the same treatment here.

``winner_team`` holds the canonical winning team and is the anchor everything
joins on. ``winner_side`` is a GENERATED column, not a second written column:
Postgres recomputes it from ``winner_team``/``home_team``/``away_team`` inside
the very same UPDATE that flips home/away, so the two can never drift. The
stale-label failure mode becomes structurally impossible rather than merely
avoided by convention.

The CASE has no ELSE on purpose. A ``winner_team`` matching neither participant
yields NULL ("we don't know") instead of being silently bucketed as a draw. The
CHECK constraint should make that unreachable, but the expression must not
*depend* on the constraint holding.

Draw vs unresolved would otherwise be ambiguous — both have no winning team — so
``status`` carries the discriminator: only a 'final' event can report 'draw'.

``winner`` is dropped rather than kept. Nothing has ever written it (verified:
the only references were the schema and a model comment), so this is free now
and never will be again.

INGEST_RUNS records the job rather than its output. /health currently infers
liveness from data freshness, which cannot separate "poller dead" from "market
genuinely quiet" — a healthy poll of a static market writes nothing, and so does
a poller that stopped. A failed run is now a row; silence is the absence of rows.

``error_message`` is written through redact() at the writer. An Odds API
HTTPStatusError embeds the API key in its message, and a table row is a worse
place to leak a credential than a log line, because rows do not rotate.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- events: stable winner encoding ------------------------------------
    op.execute("ALTER TABLE events ADD COLUMN winner_team TEXT;")
    op.execute("ALTER TABLE events ADD COLUMN resolution_source TEXT;")
    op.execute("ALTER TABLE events ADD COLUMN unresolvable_reason TEXT;")

    # Rewrite any legacy relative encoding into the stable one. Expected to
    # affect 0 rows (nothing ever wrote `winner`); written anyway so the
    # migration is correct rather than merely correct-today.
    op.execute(
        """
        UPDATE events SET winner_team = CASE
            WHEN winner = 'home' THEN home_team
            WHEN winner = 'away' THEN away_team
        END
        WHERE winner IN ('home', 'away');
        """
    )
    op.execute("ALTER TABLE events DROP COLUMN winner;")

    op.execute(
        """
        ALTER TABLE events ADD COLUMN winner_side TEXT GENERATED ALWAYS AS (
            CASE
                WHEN status <> 'final'       THEN NULL
                WHEN winner_team IS NULL     THEN 'draw'
                WHEN winner_team = home_team THEN 'home'
                WHEN winner_team = away_team THEN 'away'
            END
        ) STORED;
        """
    )

    # A recorded winner must be one of the two participants. Turns a bad
    # cross-source match against an already-resolved event into a loud failure
    # instead of silent corruption of calibration ground truth.
    op.execute(
        """
        ALTER TABLE events ADD CONSTRAINT ck_events_winner_is_a_participant
            CHECK (winner_team IS NULL OR winner_team IN (home_team, away_team));
        """
    )
    op.execute(
        """
        ALTER TABLE events ADD CONSTRAINT ck_events_final_has_scores
            CHECK (status <> 'final'
                   OR (home_score IS NOT NULL AND away_score IS NOT NULL));
        """
    )

    # Partial index driving the "what still needs resolving?" sweep, which runs
    # on every resolution pass.
    op.execute(
        """
        CREATE INDEX idx_events_pending_resolution ON events (scheduled_start)
            WHERE status = 'scheduled';
        """
    )

    # --- ingest_runs: durable job history ----------------------------------
    op.execute(
        """
        CREATE TABLE ingest_runs (
            id              BIGSERIAL   PRIMARY KEY,
            source          TEXT        NOT NULL,
            status          TEXT        NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at     TIMESTAMPTZ,
            events_seen     INT         NOT NULL DEFAULT 0,
            events_skipped  INT         NOT NULL DEFAULT 0,
            rows_attempted  INT         NOT NULL DEFAULT 0,
            rows_written    INT         NOT NULL DEFAULT 0,
            error_type      TEXT,
            error_message   TEXT,
            detail          JSONB
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_ingest_runs_source_started "
        "ON ingest_runs (source, started_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_ingest_runs_active ON ingest_runs (source) "
        "WHERE status = 'running';"
    )


def downgrade() -> None:
    """Reverse the schema.

    NOTE: this reintroduces the ambiguous home/away-relative `winner` encoding.
    Any home/away correction applied after downgrading will silently corrupt it —
    which is the entire reason `winner_team` exists.
    """
    op.execute("DROP TABLE IF EXISTS ingest_runs CASCADE;")
    op.execute("DROP INDEX IF EXISTS idx_events_pending_resolution;")
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS ck_events_final_has_scores;")
    op.execute(
        "ALTER TABLE events DROP CONSTRAINT IF EXISTS ck_events_winner_is_a_participant;"
    )
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS winner_side;")
    op.execute("ALTER TABLE events ADD COLUMN winner TEXT;")
    op.execute(
        """
        UPDATE events SET winner = CASE
            WHEN winner_team IS NULL AND status = 'final' THEN 'draw'
            WHEN winner_team = home_team THEN 'home'
            WHEN winner_team = away_team THEN 'away'
        END
        WHERE status = 'final';
        """
    )
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS unresolvable_reason;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS resolution_source;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS winner_team;")
