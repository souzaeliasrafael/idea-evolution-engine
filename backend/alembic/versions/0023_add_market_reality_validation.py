"""add market reality gates and commercial validation

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discovery_campaigns") as batch_op:
        batch_op.add_column(
            sa.Column("hard_constraints", sa.JSON(), server_default="{}", nullable=False)
        )

    with op.batch_alter_table("opportunity_signals") as batch_op:
        batch_op.add_column(
            sa.Column("commercial_signal", sa.Text(), server_default="Não informado", nullable=False)
        )
        batch_op.add_column(
            sa.Column("commercial_strength", sa.Integer(), server_default="1", nullable=False)
        )

    with op.batch_alter_table("opportunity_candidates") as batch_op:
        batch_op.add_column(sa.Column("business_case", sa.JSON(), server_default="{}", nullable=False))
        batch_op.add_column(
            sa.Column("hard_constraint_passed", sa.Boolean(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("disqualification_reasons", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(sa.Column("market_reality_score", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("market_gate_passed", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("validation_status", sa.String(12), server_default="UNTESTED", nullable=False)
        )
        batch_op.add_column(
            sa.Column("validation_result", sa.JSON(), server_default="{}", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_commercial_validation_status",
            "validation_status IN ('UNTESTED', 'PLANNED', 'RUNNING', 'VALIDATED', 'INVALIDATED', 'INCONCLUSIVE')",
        )
    # Preserve the ability to promote finalists produced by the previous
    # ranking model. New campaigns must pass the explicit market gate.
    op.execute(
        "UPDATE opportunity_candidates SET market_gate_passed = 1 "
        "WHERE status IN ('FINALIST', 'SELECTED')"
    )


def downgrade() -> None:
    with op.batch_alter_table("opportunity_candidates") as batch_op:
        batch_op.drop_constraint("ck_commercial_validation_status", type_="check")
        batch_op.drop_column("validation_result")
        batch_op.drop_column("validation_status")
        batch_op.drop_column("market_gate_passed")
        batch_op.drop_column("market_reality_score")
        batch_op.drop_column("disqualification_reasons")
        batch_op.drop_column("hard_constraint_passed")
        batch_op.drop_column("business_case")

    with op.batch_alter_table("opportunity_signals") as batch_op:
        batch_op.drop_column("commercial_strength")
        batch_op.drop_column("commercial_signal")

    with op.batch_alter_table("discovery_campaigns") as batch_op:
        batch_op.drop_column("hard_constraints")
