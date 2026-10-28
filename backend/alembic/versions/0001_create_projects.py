"""create projects table

Revision ID: 0001
Revises:
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROJECT_STATUSES = (
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


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("raw_idea", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *PROJECT_STATUSES,
                name="project_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="DRAFT",
            nullable=False,
        ),
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
    )
    op.create_index("ix_projects_status", "projects", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_table("projects")

