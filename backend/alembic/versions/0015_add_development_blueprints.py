"""add development blueprint pipeline and agent roles

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_AGENT_TYPES = ("STRUCTURER", "BUILDER", "RESEARCHER", "CRITIC", "JUDGE")
NEW_AGENT_TYPES = (
    *OLD_AGENT_TYPES,
    "PRODUCT_ARCHITECT",
    "SOLUTION_ARCHITECT",
    "TECHNICAL_CRITIC",
    "ROADMAP_PLANNER",
)
BLUEPRINT_AGENT_TYPES = NEW_AGENT_TYPES[len(OLD_AGENT_TYPES) :]


def upgrade() -> None:
    _alter_agent_enums(OLD_AGENT_TYPES, NEW_AGENT_TYPES)
    op.create_table(
        "development_blueprints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="development_blueprint_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column("architecture_alternatives", sa.Integer(), nullable=False),
        sa.Column("user_context", sa.Text(), nullable=True),
        sa.Column("max_ai_budget", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "estimated_cost", sa.Numeric(12, 6), server_default="0", nullable=False
        ),
        sa.Column("product_definition", sa.JSON(), nullable=True),
        sa.Column("architecture_options", sa.JSON(), nullable=False),
        sa.Column("technical_review", sa.JSON(), nullable=True),
        sa.Column("final_blueprint", sa.JSON(), nullable=True),
        sa.Column("agent_run_ids", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "architecture_alternatives >= 1 AND architecture_alternatives <= 3",
            name="ck_development_blueprint_alternatives",
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0", name="ck_development_blueprint_cost"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_development_blueprint_project_version"
        ),
    )
    op.create_index(
        "ix_development_blueprints_project_id",
        "development_blueprints",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_development_blueprints_status",
        "development_blueprints",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_development_blueprints_created_at",
        "development_blueprints",
        ["created_at"],
        unique=False,
    )
    _upgrade_profiles()


def downgrade() -> None:
    op.drop_index(
        "ix_development_blueprints_created_at",
        table_name="development_blueprints",
    )
    op.drop_index(
        "ix_development_blueprints_status", table_name="development_blueprints"
    )
    op.drop_index(
        "ix_development_blueprints_project_id",
        table_name="development_blueprints",
    )
    op.drop_table("development_blueprints")

    connection = op.get_bind()
    quoted = ", ".join(f"'{value}'" for value in BLUEPRINT_AGENT_TYPES)
    connection.execute(
        sa.text(f"DELETE FROM agent_prompt_versions WHERE agent IN ({quoted})")
    )
    connection.execute(sa.text(f"DELETE FROM agent_runs WHERE agent IN ({quoted})"))
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
    fallbacks = {
        "PRODUCT_ARCHITECT": "BUILDER",
        "SOLUTION_ARCHITECT": "BUILDER",
        "TECHNICAL_CRITIC": "CRITIC",
        "ROADMAP_PLANNER": "JUDGE",
    }
    for profile_id, raw_agents in rows:
        agents = json.loads(raw_agents) if isinstance(raw_agents, str) else raw_agents
        if not isinstance(agents, dict):
            continue
        for agent, fallback in fallbacks.items():
            if agent not in agents and isinstance(agents.get(fallback), dict):
                agents[agent] = dict(agents[fallback])
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
        for agent in BLUEPRINT_AGENT_TYPES:
            agents.pop(agent, None)
        connection.execute(
            sa.text("UPDATE agent_profiles SET agents = :agents WHERE id = :id"),
            {"agents": json.dumps(agents), "id": profile_id},
        )
