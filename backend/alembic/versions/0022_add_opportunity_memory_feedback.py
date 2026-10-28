"""add opportunity memory and user feedback

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discovery_campaigns") as batch_op:
        batch_op.add_column(sa.Column("memory_mode", sa.String(18), server_default="BALANCED", nullable=False))
        batch_op.create_check_constraint(
            "ck_discovery_memory_mode",
            "memory_mode IN ('NEW_ONLY', 'BALANCED', 'IMPROVE_APPROVED')",
        )

    with op.batch_alter_table("opportunity_candidates") as batch_op:
        batch_op.add_column(sa.Column("inspired_by_candidate_ids", sa.JSON(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("user_feedback", sa.String(8), server_default="PENDING", nullable=False))
        batch_op.add_column(sa.Column("feedback_tags", sa.JSON(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("feedback_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_opportunity_feedback_status",
            "user_feedback IN ('PENDING', 'APPROVED', 'REJECTED')",
        )
        batch_op.create_index("ix_opportunity_candidates_user_feedback", ["user_feedback"])


def downgrade() -> None:
    with op.batch_alter_table("opportunity_candidates") as batch_op:
        batch_op.drop_index("ix_opportunity_candidates_user_feedback")
        batch_op.drop_constraint("ck_opportunity_feedback_status", type_="check")
        batch_op.drop_column("feedback_at")
        batch_op.drop_column("feedback_note")
        batch_op.drop_column("feedback_tags")
        batch_op.drop_column("user_feedback")
        batch_op.drop_column("inspired_by_candidate_ids")

    with op.batch_alter_table("discovery_campaigns") as batch_op:
        batch_op.drop_constraint("ck_discovery_memory_mode", type_="check")
        batch_op.drop_column("memory_mode")
