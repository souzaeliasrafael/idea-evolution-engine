"""add persisted Judge chat turns

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "judge_chat_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("input_mode", sa.String(length=10), server_default="TEXT", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_rounds", sa.Integer(), server_default="1", nullable=False),
        sa.Column("judge_response", sa.Text(), nullable=True),
        sa.Column("stop_reason", sa.String(length=40), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_before", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("cost_after", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("input_mode IN ('TEXT', 'VOICE')", name="ck_judge_chat_turn_input_mode"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'NO_DECISION', 'CANCELLED', 'BUDGET_STOPPED', 'FAILED')",
            name="ck_judge_chat_turn_status",
        ),
        sa.CheckConstraint("requested_rounds >= 1", name="ck_judge_chat_turn_requested_rounds"),
        sa.CheckConstraint("cost_before >= 0 AND cost_after >= 0", name="ck_judge_chat_turn_costs"),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "decision_id", "status", "created_at"):
        op.create_index(
            f"ix_judge_chat_turns_{column}",
            "judge_chat_turns",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(("project_id", "decision_id", "status", "created_at")):
        op.drop_index(f"ix_judge_chat_turns_{column}", table_name="judge_chat_turns")
    op.drop_table("judge_chat_turns")
