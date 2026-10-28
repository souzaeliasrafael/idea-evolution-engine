"""add human review, experiments, and agent profiles

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_PROJECT_STATUSES = (
    "DRAFT",
    "STRUCTURING",
    "RESEARCHING",
    "DEBATING",
    "VALIDATING",
    "PIVOTING",
    "APPROVED",
    "DISCARDED",
    "BUILDING",
)
PROJECT_STATUSES = (
    "DRAFT",
    "STRUCTURING",
    "RESEARCHING",
    "DEBATING",
    "VALIDATING",
    "PIVOTING",
    "AWAITING_CONFIRMATION",
    "APPROVED",
    "DISCARDED",
    "BUILDING",
)
HUMAN_REVIEW_STATUSES = ("NOT_REQUIRED", "PENDING", "ACCEPTED", "OVERRIDDEN")
HUMAN_REVIEW_ACTIONS = (
    "ACCEPT_RECOMMENDATION",
    "CONTINUE_ANYWAY",
    "MANUAL_PIVOT",
)
EXPERIMENT_STATUSES = ("PLANNED", "RUNNING", "COMPLETED", "CANCELLED")
EXPERIMENT_OUTCOMES = ("SUCCESS", "FAILURE", "INCONCLUSIVE")


def _project_status_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(
        *values,
        name="project_status",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("project_status", type_="check")
        batch_op.alter_column(
            "status",
            existing_type=_project_status_enum(OLD_PROJECT_STATUSES),
            type_=_project_status_enum(PROJECT_STATUSES),
            existing_nullable=False,
            existing_server_default="DRAFT",
        )
        batch_op.add_column(
            sa.Column("agent_profile_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_projects_agent_profile_id_agent_profiles",
            "agent_profiles",
            ["agent_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_projects_agent_profile_id", ["agent_profile_id"], unique=False
        )

    with op.batch_alter_table("decisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "human_review_status",
                sa.Enum(
                    *HUMAN_REVIEW_STATUSES,
                    name="human_review_status",
                    native_enum=False,
                    create_constraint=True,
                ),
                server_default="NOT_REQUIRED",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "human_action",
                sa.Enum(
                    *HUMAN_REVIEW_ACTIONS,
                    name="human_review_action",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("human_note", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_decisions_human_review_status",
            ["human_review_status"],
            unique=False,
        )

    op.create_table(
        "experiments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=True),
        sa.Column("experiment_type", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("success_metric", sa.Text(), nullable=True),
        sa.Column("success_threshold", sa.Text(), nullable=True),
        sa.Column(
            "estimated_cost",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "actual_cost",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                *EXPERIMENT_STATUSES,
                name="experiment_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="PLANNED",
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                *EXPERIMENT_OUTCOMES,
                name="experiment_outcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "actual_cost >= 0", name="ck_experiment_actual_cost"
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0", name="ck_experiment_estimated_cost"
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"], ["hypotheses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index(
        "ix_experiments_created_at", "experiments", ["created_at"], unique=False
    )
    op.create_index(
        "ix_experiments_hypothesis_id",
        "experiments",
        ["hypothesis_id"],
        unique=False,
    )
    op.create_index(
        "ix_experiments_project_id", "experiments", ["project_id"], unique=False
    )
    op.create_index(
        "ix_experiments_status", "experiments", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_experiments_status", table_name="experiments")
    op.drop_index("ix_experiments_project_id", table_name="experiments")
    op.drop_index("ix_experiments_hypothesis_id", table_name="experiments")
    op.drop_index("ix_experiments_created_at", table_name="experiments")
    op.drop_table("experiments")

    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_index("ix_decisions_human_review_status")
        batch_op.drop_constraint("human_review_action", type_="check")
        batch_op.drop_constraint("human_review_status", type_="check")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("human_note")
        batch_op.drop_column("human_action")
        batch_op.drop_column("human_review_status")

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_index("ix_projects_agent_profile_id")
        batch_op.drop_constraint(
            "fk_projects_agent_profile_id_agent_profiles", type_="foreignkey"
        )
        batch_op.drop_column("agent_profile_id")
        batch_op.drop_constraint("project_status", type_="check")
        batch_op.alter_column(
            "status",
            existing_type=_project_status_enum(PROJECT_STATUSES),
            type_=_project_status_enum(OLD_PROJECT_STATUSES),
            existing_nullable=False,
            existing_server_default="DRAFT",
        )

    op.drop_table("agent_profiles")
