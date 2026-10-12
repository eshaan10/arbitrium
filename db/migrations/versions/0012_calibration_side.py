"""calibration_history.side: which contract the call bought

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-12

A call is "Buy Yes" or "Buy No" on ``subject_team``'s market, and only the pair
says what was predicted: Buy No on the Packers is a call that the Packers LOSE.
The row stored the team but not the side, so every No call read as "this team
wins" to anything that compared ``subject_team`` with the winner.

NULL means "not recorded": rows written before this column. The calibration
pass fills them by replaying the recommendation at ``flagged_at`` (see
``grading.backfill_sides``) and leaves a row NULL when the replay does not
reproduce the stored team and price, rather than guess.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE calibration_history
            ADD COLUMN side TEXT CHECK (side IN ('yes', 'no'));
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calibration_history DROP COLUMN IF EXISTS side;")
