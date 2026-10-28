"""add context supplied for the next orchestration round

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("next_round_context", sa.Text(), nullable=True))
    with op.batch_alter_table("rounds") as batch_op:
        batch_op.add_column(sa.Column("human_context", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rounds") as batch_op:
        batch_op.drop_column("human_context")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("next_round_context")
