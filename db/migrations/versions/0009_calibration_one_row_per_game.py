"""narrow the calibration uniqueness to one row per game per origin

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10

0008 made ``calibration_history`` unique on (event_id, subject_team, origin).
That is wrong, and it only became obvious when wiring live recording.

A recommendation's SIDE moves over an event's life as prices drift — observed
directly: the Cardinals/Panthers game reconstructed to Arizona at the earliest
actionable moment and was showing Carolina by kickoff. Under the old index those
are two different ``subject_team`` values, so recording live at both moments
would have written TWO rows for ONE game.

That is precisely the failure the whole calibration design is built to avoid.
The sample-size gate counts rows, so double-counting a game would inflate n,
shrink every confidence interval, and make a curve look better evidenced than it
is — the same "two sides of a two-way market are one bet" error, arriving
through the back door.

One row per (event_id, origin). ``subject_team`` stays as data, recording WHICH
side was called, but it no longer participates in identity.

The two origins remain separate rows on purpose: a live prospective record and a
reconstructed backtest are different kinds of evidence and are never merged.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Collapse any pre-existing duplicates before the tighter index can apply.
    # Keeps the EARLIEST row per (event, origin): a track record should preserve
    # what was first said, not what was said last with more information.
    op.execute(
        """
        DELETE FROM calibration_history a
        USING calibration_history b
        WHERE a.event_id = b.event_id
          AND a.origin   = b.origin
          AND (a.flagged_at, a.id) > (b.flagged_at, b.id);
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_calibration_unique_prediction;")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_calibration_one_per_game
            ON calibration_history (event_id, origin);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calibration_one_per_game;")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_calibration_unique_prediction
            ON calibration_history (event_id, subject_team, origin);
        """
    )
