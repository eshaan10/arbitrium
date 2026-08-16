"""add calibration provenance + closing-line-value columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10

``calibration_history`` was declared in 0001 with enough columns to record a
prediction and grade it, but not enough to say WHERE the prediction came from or
how the price moved afterwards. Both matter.

ORIGIN. Predictions come from two places. A 'live' row was written before the
game, from data available at the time — a genuine prospective record. A
'reconstructed' row was derived afterwards from append-only snapshot history;
that is legitimate (it reads only pre-kickoff snapshots) and it is the only way
to build a usable sample in a first season, but it is a BACKTEST. Merging the two
into one headline number would let hindsight-free and hindsight-adjacent evidence
masquerade as the same thing, so the distinction is stored and always reported.

SUBJECT_TEAM. ``predicted_prob`` is a probability *of something*, and without
naming the team the row cannot be audited or re-derived later. Stored as the
canonical team name for the same reason ``odds_snapshots.team`` and
``events.winner_team`` are: home/away is provisional and can be re-labelled.

CLOSING-LINE VALUE. ``entry_prob`` is what Kalshi charged when the call was made;
``closing_prob`` is Kalshi's last price before kickoff. Their difference is the
only self-assessment available before enough games resolve — it needs no outcome
at all, just price history, so it produces signal months earlier than calibration
can. Nullable because a game that has not kicked off yet has no close, and that
is a real state rather than a missing value.

No CHECK constraints: the schema has none anywhere and adding them to one table
would be inconsistent. Allowed values are documented in
``arbitrium.calibration``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE calibration_history
            ADD COLUMN origin       TEXT NOT NULL DEFAULT 'live',
            ADD COLUMN subject_team TEXT,
            ADD COLUMN entry_prob   NUMERIC(6,4),
            ADD COLUMN closing_prob NUMERIC(6,4);
        """
    )
    # CLV is stored rather than computed on read so a historical row keeps the
    # value as measured, even if the definition is later refined.
    op.execute("ALTER TABLE calibration_history ADD COLUMN clv NUMERIC(7,4);")

    # One prediction per (event, subject, origin): re-running a reconstruction
    # must update the existing row rather than pile up duplicates that would
    # silently inflate the sample size the gate depends on.
    op.execute(
        """
        CREATE UNIQUE INDEX idx_calibration_unique_prediction
            ON calibration_history (event_id, subject_team, origin);
        """
    )
    op.execute(
        """
        CREATE INDEX idx_calibration_ungraded ON calibration_history (event_id)
            WHERE outcome_correct IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calibration_ungraded;")
    op.execute("DROP INDEX IF EXISTS idx_calibration_unique_prediction;")
    op.execute(
        """
        ALTER TABLE calibration_history
            DROP COLUMN IF EXISTS clv,
            DROP COLUMN IF EXISTS closing_prob,
            DROP COLUMN IF EXISTS entry_prob,
            DROP COLUMN IF EXISTS subject_team,
            DROP COLUMN IF EXISTS origin;
        """
    )
