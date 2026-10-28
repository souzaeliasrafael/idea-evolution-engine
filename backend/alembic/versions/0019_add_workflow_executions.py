"""add durable workflow execution coordination

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="IDLE", nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("current_agent", sa.String(length=18), nullable=True),
        sa.Column("workflow_stage", sa.String(length=160), nullable=True),
        sa.Column("current_round", sa.Integer(), nullable=True),
        sa.Column("round_position", sa.Integer(), nullable=True),
        sa.Column("requested_rounds", sa.Integer(), nullable=True),
        sa.Column("agent_iteration", sa.Integer(), nullable=True),
        sa.Column("agent_iterations", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('IDLE', 'RUNNING', 'CANCELLING')",
            name="ck_workflow_executions_status",
        ),
        sa.CheckConstraint(
            "current_round IS NULL OR current_round >= 1",
            name="ck_workflow_executions_current_round",
        ),
        sa.CheckConstraint(
            "requested_rounds IS NULL OR requested_rounds >= 1",
            name="ck_workflow_executions_requested_rounds",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    for column in ("status", "owner_id", "heartbeat_at"):
        op.create_index(
            f"ix_workflow_executions_{column}",
            "workflow_executions",
            [column],
            unique=False,
        )
    op.execute(
        sa.text(
            "INSERT INTO workflow_executions (project_id, status, cancellation_requested) "
            "SELECT id, 'IDLE', 0 FROM projects"
        )
    )


def downgrade() -> None:
    for column in reversed(("status", "owner_id", "heartbeat_at")):
        op.drop_index(f"ix_workflow_executions_{column}", table_name="workflow_executions")
    op.drop_table("workflow_executions")
