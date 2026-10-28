"""add orchestration rounds

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROUND_STATUSES = ("RUNNING", "COMPLETED", "FAILED")
DECISION_TYPES = ("REFINE", "RESEARCH", "TEST", "PIVOT", "APPROVE", "DISCARD")


def upgrade() -> None:
    op.create_table(
        "rounds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *ROUND_STATUSES,
                name="round_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("starting_version_id", sa.String(length=36), nullable=False),
        sa.Column("resulting_version_id", sa.String(length=36), nullable=True),
        sa.Column(
            "decision",
            sa.Enum(
                *DECISION_TYPES,
                name="round_decision_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resulting_version_id"], ["idea_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["starting_version_id"], ["idea_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "round_number", name="uq_round_project_number"
        ),
    )
    op.create_index("ix_rounds_project_id", "rounds", ["project_id"], unique=False)
    op.create_index("ix_rounds_started_at", "rounds", ["started_at"], unique=False)
    op.create_index("ix_rounds_status", "rounds", ["status"], unique=False)
    op.create_index(
        "ix_agent_runs_round_id", "agent_runs", ["round_id"], unique=False
    )
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.create_foreign_key(
            "fk_agent_runs_round_id_rounds",
            "rounds",
            ["round_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_agent_runs_round_id_rounds", type_="foreignkey"
        )
    op.drop_index("ix_agent_runs_round_id", table_name="agent_runs")
    op.drop_index("ix_rounds_status", table_name="rounds")
    op.drop_index("ix_rounds_started_at", table_name="rounds")
    op.drop_index("ix_rounds_project_id", table_name="rounds")
    op.drop_table("rounds")
