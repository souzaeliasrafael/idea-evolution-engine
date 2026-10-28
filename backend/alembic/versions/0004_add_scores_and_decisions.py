"""add scores and decisions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DECISION_TYPES = ("REFINE", "RESEARCH", "TEST", "PIVOT", "APPROVE", "DISCARD")


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("idea_version_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["idea_version_id"], ["idea_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scores_agent_run_id", "scores", ["agent_run_id"], unique=False)
    op.create_index("ix_scores_created_at", "scores", ["created_at"], unique=False)
    op.create_index(
        "ix_scores_idea_version_id", "scores", ["idea_version_id"], unique=False
    )
    op.create_index("ix_scores_project_id", "scores", ["project_id"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=True),
        sa.Column(
            "decision",
            sa.Enum(
                *DECISION_TYPES,
                name="decision_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("from_version_id", sa.String(length=36), nullable=False),
        sa.Column("to_version_id", sa.String(length=36), nullable=True),
        sa.Column("score_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("critical_blockers", sa.JSON(), nullable=False),
        sa.Column("most_important_unknowns", sa.JSON(), nullable=False),
        sa.Column("next_actions", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["from_version_id"], ["idea_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["to_version_id"], ["idea_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id"),
        sa.UniqueConstraint("score_id"),
    )
    op.create_index(
        "ix_decisions_created_at", "decisions", ["created_at"], unique=False
    )
    op.create_index(
        "ix_decisions_decision", "decisions", ["decision"], unique=False
    )
    op.create_index(
        "ix_decisions_project_id", "decisions", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_decisions_project_id", table_name="decisions")
    op.drop_index("ix_decisions_decision", table_name="decisions")
    op.drop_index("ix_decisions_created_at", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_scores_project_id", table_name="scores")
    op.drop_index("ix_scores_idea_version_id", table_name="scores")
    op.drop_index("ix_scores_created_at", table_name="scores")
    op.drop_index("ix_scores_agent_run_id", table_name="scores")
    op.drop_table("scores")

