"""add versioned discovery prompts

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("agent IN ('OPPORTUNITY_SCOUT', 'IDEA_GENERATOR', 'OPPORTUNITY_RESEARCHER', 'PORTFOLIO_JUDGE')", name="ck_discovery_prompt_type"),
        sa.UniqueConstraint("agent", "version", name="uq_discovery_prompt_agent_version"),
    )
    for column in ("agent", "is_active", "created_at"):
        op.create_index(f"ix_discovery_prompt_versions_{column}", "discovery_prompt_versions", [column])


def downgrade() -> None:
    op.drop_table("discovery_prompt_versions")
