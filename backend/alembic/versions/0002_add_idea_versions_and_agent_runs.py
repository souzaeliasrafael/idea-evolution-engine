"""add idea versions and agent runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AGENT_TYPES = ("STRUCTURER", "BUILDER", "RESEARCHER", "CRITIC", "JUDGE")


def upgrade() -> None:
    agent_type = sa.Enum(
        *AGENT_TYPES,
        name="agent_type",
        native_enum=False,
        create_constraint=True,
    )

    op.create_table(
        "idea_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("reason_for_change", sa.Text(), nullable=False),
        sa.Column("created_by", agent_type, nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("concept", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["idea_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_idea_versions_project_version"
        ),
    )
    op.create_index(
        "ix_idea_versions_project_id", "idea_versions", ["project_id"], unique=False
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("round_id", sa.String(length=36), nullable=True),
        sa.Column("agent", agent_type, nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "estimated_cost",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("execution_time", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_agent", "agent_runs", ["agent"], unique=False)
    op.create_index(
        "ix_agent_runs_created_at", "agent_runs", ["created_at"], unique=False
    )
    op.create_index(
        "ix_agent_runs_project_id", "agent_runs", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_project_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_idea_versions_project_id", table_name="idea_versions")
    op.drop_table("idea_versions")

