"""add traceable discovery handoffs

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["discovery_campaigns.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["opportunity_candidates.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("project_id", name="uq_discovery_handoff_project"),
        sa.UniqueConstraint("candidate_id", name="uq_discovery_handoff_candidate"),
    )
    op.create_index(
        "ix_discovery_handoffs_project_id", "discovery_handoffs", ["project_id"], unique=True
    )
    op.create_index(
        "ix_discovery_handoffs_campaign_id", "discovery_handoffs", ["campaign_id"]
    )
    op.create_index(
        "ix_discovery_handoffs_candidate_id", "discovery_handoffs", ["candidate_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("discovery_handoffs")
