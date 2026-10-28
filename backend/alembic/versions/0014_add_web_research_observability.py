"""add web research observability to agent runs

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "web_search_calls", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "tool_cost", sa.Numeric(12, 6), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("web_sources", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("web_sources")
        batch_op.drop_column("tool_cost")
        batch_op.drop_column("web_search_calls")
