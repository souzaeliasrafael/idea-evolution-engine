"""add experiment evidence traceability and focused reassessment

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_EVIDENCE_ORIGINS = ("USER", "RESEARCHER")
NEW_EVIDENCE_ORIGINS = (*OLD_EVIDENCE_ORIGINS, "EXPERIMENT")
REASSESSMENT_STATUSES = (
    "NOT_REQUESTED",
    "PENDING",
    "COMPLETED",
    "FAILED",
    "SKIPPED_BUDGET",
)


def _evidence_origin_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(
        *values,
        name="evidence_origin",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column(
            "origin",
            existing_type=_evidence_origin_enum(OLD_EVIDENCE_ORIGINS),
            type_=_evidence_origin_enum(NEW_EVIDENCE_ORIGINS),
            existing_nullable=False,
        )

    with op.batch_alter_table("experiments") as batch_op:
        batch_op.add_column(sa.Column("observed_value", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("sample_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("methodology", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("limitations", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("evidence_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("evidence_quality", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "affected_criteria",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "reassessment_status",
                sa.Enum(
                    *REASSESSMENT_STATUSES,
                    name="experiment_reassessment_status",
                    native_enum=False,
                    create_constraint=True,
                ),
                server_default="NOT_REQUESTED",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("previous_score", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("previous_confidence", sa.Float(), nullable=True)
        )
        batch_op.add_column(sa.Column("reassessed_score", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("reassessed_confidence", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reassessment_score_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reassessment_decision_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reassessment_error", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_experiment_evidence_quality",
            "evidence_quality IS NULL OR (evidence_quality >= 0 AND evidence_quality <= 5)",
        )
        batch_op.create_check_constraint(
            "ck_experiment_sample_size",
            "sample_size IS NULL OR sample_size > 0",
        )
        batch_op.create_foreign_key(
            "fk_experiments_evidence_id_evidence",
            "evidence",
            ["evidence_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_experiments_reassessment_score_id_scores",
            "scores",
            ["reassessment_score_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_experiments_reassessment_decision_id_decisions",
            "decisions",
            ["reassessment_decision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_experiments_evidence_id", ["evidence_id"]
        )
        batch_op.create_unique_constraint(
            "uq_experiments_reassessment_score_id", ["reassessment_score_id"]
        )
        batch_op.create_unique_constraint(
            "uq_experiments_reassessment_decision_id",
            ["reassessment_decision_id"],
        )
        batch_op.create_index(
            "ix_experiments_evidence_id", ["evidence_id"], unique=False
        )
        batch_op.create_index(
            "ix_experiments_reassessment_status",
            ["reassessment_status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("experiments") as batch_op:
        batch_op.drop_index("ix_experiments_reassessment_status")
        batch_op.drop_index("ix_experiments_evidence_id")
        batch_op.drop_constraint(
            "uq_experiments_reassessment_decision_id", type_="unique"
        )
        batch_op.drop_constraint(
            "uq_experiments_reassessment_score_id", type_="unique"
        )
        batch_op.drop_constraint("uq_experiments_evidence_id", type_="unique")
        batch_op.drop_constraint(
            "fk_experiments_reassessment_decision_id_decisions",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_experiments_reassessment_score_id_scores", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_experiments_evidence_id_evidence", type_="foreignkey"
        )
        batch_op.drop_constraint("ck_experiment_sample_size", type_="check")
        batch_op.drop_constraint("ck_experiment_evidence_quality", type_="check")
        batch_op.drop_constraint(
            "experiment_reassessment_status", type_="check"
        )
        batch_op.drop_column("reassessment_error")
        batch_op.drop_column("reassessment_decision_id")
        batch_op.drop_column("reassessment_score_id")
        batch_op.drop_column("reassessed_confidence")
        batch_op.drop_column("reassessed_score")
        batch_op.drop_column("previous_confidence")
        batch_op.drop_column("previous_score")
        batch_op.drop_column("reassessment_status")
        batch_op.drop_column("affected_criteria")
        batch_op.drop_column("evidence_quality")
        batch_op.drop_column("evidence_id")
        batch_op.drop_column("limitations")
        batch_op.drop_column("methodology")
        batch_op.drop_column("sample_size")
        batch_op.drop_column("observed_value")

    op.execute("DELETE FROM evidence WHERE origin = 'EXPERIMENT'")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column(
            "origin",
            existing_type=_evidence_origin_enum(NEW_EVIDENCE_ORIGINS),
            type_=_evidence_origin_enum(OLD_EVIDENCE_ORIGINS),
            existing_nullable=False,
        )
