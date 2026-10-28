"""add versioned agent prompt overrides

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AGENT_TYPES = ("STRUCTURER", "BUILDER", "RESEARCHER", "CRITIC", "JUDGE")


def upgrade() -> None:
    op.create_table(
        "agent_prompt_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "agent",
            sa.Enum(
                *AGENT_TYPES,
                name="agent_prompt_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default="1", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent", "version", name="uq_agent_prompt_versions_agent_version"
        ),
    )
    op.create_index(
        "ix_agent_prompt_versions_agent",
        "agent_prompt_versions",
        ["agent"],
        unique=False,
    )
    op.create_index(
        "ix_agent_prompt_versions_is_active",
        "agent_prompt_versions",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_agent_prompt_versions_created_at",
        "agent_prompt_versions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_prompt_versions_created_at", table_name="agent_prompt_versions"
    )
    op.drop_index(
        "ix_agent_prompt_versions_is_active", table_name="agent_prompt_versions"
    )
    op.drop_index(
        "ix_agent_prompt_versions_agent", table_name="agent_prompt_versions"
    )
    op.drop_table("agent_prompt_versions")
