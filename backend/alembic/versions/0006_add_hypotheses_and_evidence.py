"""add hypothesis register and evidence ledger

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


HYPOTHESIS_STATUSES = ("OPEN", "PARTIAL", "VALIDATED", "REJECTED")
EPISTEMIC_CLASSIFICATIONS = (
    "FACT",
    "ASSUMPTION",
    "INFERENCE",
    "OPINION",
    "UNKNOWN",
)
HYPOTHESIS_ORIGINS = ("USER", "STRUCTURER", "BUILDER", "RESEARCHER")
EVIDENCE_DIRECTIONS = ("SUPPORT", "CONTRADICT", "NEUTRAL")
EVIDENCE_ORIGINS = ("USER", "RESEARCHER")


def upgrade() -> None:
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *HYPOTHESIS_STATUSES,
                name="hypothesis_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "epistemic_classification",
            sa.Enum(
                *EPISTEMIC_CLASSIFICATIONS,
                name="epistemic_classification",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "origin",
            sa.Enum(
                *HYPOTHESIS_ORIGINS,
                name="hypothesis_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_version_id", sa.String(length=36), nullable=True),
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
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_hypothesis_confidence",
        ),
        sa.CheckConstraint(
            "impact >= 1 AND impact <= 10", name="ck_hypothesis_impact"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["idea_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "sequence", name="uq_hypothesis_project_sequence"
        ),
        sa.UniqueConstraint(
            "project_id", "statement", name="uq_hypothesis_project_statement"
        ),
    )
    op.create_index(
        "ix_hypotheses_created_at", "hypotheses", ["created_at"], unique=False
    )
    op.create_index(
        "ix_hypotheses_project_id", "hypotheses", ["project_id"], unique=False
    )
    op.create_index(
        "ix_hypotheses_status", "hypotheses", ["status"], unique=False
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                *EVIDENCE_DIRECTIONS,
                name="evidence_direction",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column(
            "epistemic_classification",
            sa.Enum(
                *EPISTEMIC_CLASSIFICATIONS,
                name="evidence_epistemic_classification",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column(
            "origin",
            sa.Enum(
                *EVIDENCE_ORIGINS,
                name="evidence_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 5", name="ck_evidence_strength"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"], ["hypotheses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "sequence", name="uq_evidence_project_sequence"
        ),
    )
    op.create_index(
        "ix_evidence_agent_run_id", "evidence", ["agent_run_id"], unique=False
    )
    op.create_index(
        "ix_evidence_created_at", "evidence", ["created_at"], unique=False
    )
    op.create_index(
        "ix_evidence_direction", "evidence", ["direction"], unique=False
    )
    op.create_index(
        "ix_evidence_hypothesis_id", "evidence", ["hypothesis_id"], unique=False
    )
    op.create_index(
        "ix_evidence_project_id", "evidence", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_project_id", table_name="evidence")
    op.drop_index("ix_evidence_hypothesis_id", table_name="evidence")
    op.drop_index("ix_evidence_direction", table_name="evidence")
    op.drop_index("ix_evidence_created_at", table_name="evidence")
    op.drop_index("ix_evidence_agent_run_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_hypotheses_status", table_name="hypotheses")
    op.drop_index("ix_hypotheses_project_id", table_name="hypotheses")
    op.drop_index("ix_hypotheses_created_at", table_name="hypotheses")
    op.drop_table("hypotheses")
