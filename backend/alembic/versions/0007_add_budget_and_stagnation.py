"""add project budgets and stagnation markers

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "total_cost",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "max_ai_budget", sa.Numeric(precision=12, scale=6), nullable=True
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "stagnation_detected",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "rounds",
        sa.Column(
            "budget_limit_reached",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "rounds",
        sa.Column(
            "stagnation_detected",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("rounds", "stagnation_detected")
    op.drop_column("rounds", "budget_limit_reached")
    op.drop_column("projects", "stagnation_detected")
    op.drop_column("projects", "max_ai_budget")
    op.drop_column("projects", "total_cost")
