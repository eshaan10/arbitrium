"""create calibration_history

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

Declared in Phase 1 so migrations are structurally complete; populated in Phase 3.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calibration_history (
            id                BIGSERIAL   PRIMARY KEY,
            event_id          UUID        NOT NULL REFERENCES events(id),
            divergence_score  NUMERIC(6,4) NOT NULL,
            predicted_prob    NUMERIC(6,4) NOT NULL,
            confidence_band   TEXT        NOT NULL,
            outcome_correct   BOOLEAN,
            flagged_at        TIMESTAMPTZ NOT NULL,
            graded_at         TIMESTAMPTZ
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_calibration_confidence_band "
        "ON calibration_history (confidence_band);"
    )
    op.execute("CREATE INDEX idx_calibration_event_id ON calibration_history (event_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calibration_history CASCADE;")
