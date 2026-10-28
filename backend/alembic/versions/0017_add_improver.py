"""add post-judge improver and persisted improvement plans

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_AGENT_TYPES = (
    "STRUCTURER",
    "BUILDER",
    "RESEARCHER",
    "CRITIC",
    "JUDGE",
    "PRODUCT_ARCHITECT",
    "SOLUTION_ARCHITECT",
    "TECHNICAL_CRITIC",
    "ROADMAP_PLANNER",
)
NEW_AGENT_TYPES = (*OLD_AGENT_TYPES, "IMPROVER")


def upgrade() -> None:
    _alter_agent_enums(OLD_AGENT_TYPES, NEW_AGENT_TYPES)
    op.create_table(
        "improvement_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("round_id", sa.String(length=36), nullable=True),
        sa.Column("idea_version_id", sa.String(length=36), nullable=False),
        sa.Column("score_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_score", sa.Integer(), nullable=False),
        sa.Column("source_confidence", sa.Float(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_score >= 0 AND source_score <= 100",
            name="ck_improvement_plan_score",
        ),
        sa.CheckConstraint(
            "source_confidence >= 0 AND source_confidence <= 1",
            name="ck_improvement_plan_confidence",
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["idea_version_id"], ["idea_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_improvement_plan_project_version"
        ),
    )
    for column in ("project_id", "round_id", "score_id", "decision_id", "created_at"):
        op.create_index(
            f"ix_improvement_plans_{column}",
            "improvement_plans",
            [column],
            unique=False,
        )
    _upgrade_profiles()


def downgrade() -> None:
    for column in reversed(("project_id", "round_id", "score_id", "decision_id", "created_at")):
        op.drop_index(f"ix_improvement_plans_{column}", table_name="improvement_plans")
    op.drop_table("improvement_plans")
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM agent_prompt_versions WHERE agent = 'IMPROVER'")
    )
    connection.execute(sa.text("DELETE FROM agent_runs WHERE agent = 'IMPROVER'"))
    _downgrade_profiles()
    _alter_agent_enums(NEW_AGENT_TYPES, OLD_AGENT_TYPES)


def _alter_agent_enums(old_values: tuple[str, ...], new_values: tuple[str, ...]) -> None:
    old_agent_type = sa.Enum(
        *old_values, name="agent_type", native_enum=False, create_constraint=True
    )
    new_agent_type = sa.Enum(
        *new_values, name="agent_type", native_enum=False, create_constraint=True
    )
    with op.batch_alter_table("idea_versions") as batch_op:
        batch_op.alter_column(
            "created_by",
            existing_type=old_agent_type,
            type_=new_agent_type,
            existing_nullable=False,
        )
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "agent",
            existing_type=old_agent_type,
            type_=new_agent_type,
            existing_nullable=False,
        )
    old_prompt_type = sa.Enum(
        *old_values,
        name="agent_prompt_type",
        native_enum=False,
        create_constraint=True,
    )
    new_prompt_type = sa.Enum(
        *new_values,
        name="agent_prompt_type",
        native_enum=False,
        create_constraint=True,
    )
    with op.batch_alter_table("agent_prompt_versions") as batch_op:
        batch_op.alter_column(
            "agent",
            existing_type=old_prompt_type,
            type_=new_prompt_type,
            existing_nullable=False,
        )


def _upgrade_profiles() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, agents FROM agent_profiles")).all()
    for profile_id, raw_agents in rows:
        agents = json.loads(raw_agents) if isinstance(raw_agents, str) else raw_agents
        if not isinstance(agents, dict):
            continue
        if "IMPROVER" not in agents and isinstance(agents.get("BUILDER"), dict):
            agents["IMPROVER"] = dict(agents["BUILDER"])
        connection.execute(
            sa.text("UPDATE agent_profiles SET agents = :agents WHERE id = :id"),
            {"agents": json.dumps(agents), "id": profile_id},
        )


def _downgrade_profiles() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, agents FROM agent_profiles")).all()
    for profile_id, raw_agents in rows:
        agents = json.loads(raw_agents) if isinstance(raw_agents, str) else raw_agents
        if not isinstance(agents, dict):
            continue
        agents.pop("IMPROVER", None)
        connection.execute(
            sa.text("UPDATE agent_profiles SET agents = :agents WHERE id = :id"),
            {"agents": json.dumps(agents), "id": profile_id},
        )
