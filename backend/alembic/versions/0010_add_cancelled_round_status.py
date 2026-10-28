"""add cancelled orchestration round status

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_ROUND_STATUSES = ("RUNNING", "COMPLETED", "FAILED")
ROUND_STATUSES = (*OLD_ROUND_STATUSES, "CANCELLED")


def _round_status_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(
        *values,
        name="round_status",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("rounds") as batch_op:
        batch_op.drop_constraint("round_status", type_="check")
        batch_op.alter_column(
            "status",
            existing_type=_round_status_enum(OLD_ROUND_STATUSES),
            type_=_round_status_enum(ROUND_STATUSES),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE rounds SET status = 'FAILED', "
            "error = COALESCE(error, 'Cancelled by user') "
            "WHERE status = 'CANCELLED'"
        )
    )
    with op.batch_alter_table("rounds") as batch_op:
        batch_op.drop_constraint("round_status", type_="check")
        batch_op.alter_column(
            "status",
            existing_type=_round_status_enum(ROUND_STATUSES),
            type_=_round_status_enum(OLD_ROUND_STATUSES),
            existing_nullable=False,
        )
