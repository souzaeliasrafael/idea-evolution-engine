"""add per-project agent execution plan

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_AGENT_PLAN = '{"builder": 1, "researcher": 1, "critic": 1}'


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "agent_plan",
                sa.JSON(),
                server_default=DEFAULT_AGENT_PLAN,
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("agent_plan")
