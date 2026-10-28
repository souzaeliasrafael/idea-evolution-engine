"""add criticisms

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CRITICISM_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def upgrade() -> None:
    op.create_table(
        "criticisms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("idea_version_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                *CRITICISM_SEVERITIES,
                name="criticism_severity",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("affected_hypotheses", sa.JSON(), nullable=False),
        sa.Column("evidence_needed", sa.Text(), nullable=False),
        sa.Column("condition_that_refutes_criticism", sa.Text(), nullable=False),
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
    op.create_index(
        "ix_criticisms_agent_run_id", "criticisms", ["agent_run_id"], unique=False
    )
    op.create_index(
        "ix_criticisms_created_at", "criticisms", ["created_at"], unique=False
    )
    op.create_index(
        "ix_criticisms_idea_version_id",
        "criticisms",
        ["idea_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_criticisms_project_id", "criticisms", ["project_id"], unique=False
    )
    op.create_index(
        "ix_criticisms_severity", "criticisms", ["severity"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_criticisms_severity", table_name="criticisms")
    op.drop_index("ix_criticisms_project_id", table_name="criticisms")
    op.drop_index("ix_criticisms_idea_version_id", table_name="criticisms")
    op.drop_index("ix_criticisms_created_at", table_name="criticisms")
    op.drop_index("ix_criticisms_agent_run_id", table_name="criticisms")
    op.drop_table("criticisms")

