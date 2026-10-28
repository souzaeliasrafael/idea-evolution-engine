"""add provider-aware financial observability

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("provider", sa.String(length=100), server_default="unknown", nullable=False)
        )
        batch_op.add_column(
            sa.Column("cached_input_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("reasoning_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_index("ix_agent_runs_provider", ["provider"], unique=False)

    op.create_table(
        "provider_cost_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_reference", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "PROVIDER_API",
                "MANUAL",
                name="billing_cost_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("line_item", sa.String(length=300), nullable=True),
        sa.Column("external_project_id", sa.String(length=200), nullable=True),
        sa.Column("external_api_key_id", sa.String(length=200), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("quantity_unit", sa.String(length=50), nullable=True),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
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
        sa.UniqueConstraint("external_reference"),
    )
    op.create_index("ix_provider_cost_entries_provider", "provider_cost_entries", ["provider"])
    op.create_index("ix_provider_cost_entries_source", "provider_cost_entries", ["source"])
    op.create_index("ix_provider_cost_entries_period_start", "provider_cost_entries", ["period_start"])
    op.create_index("ix_provider_cost_entries_period_end", "provider_cost_entries", ["period_end"])
    op.create_index("ix_provider_cost_entries_model", "provider_cost_entries", ["model"])

    op.create_table(
        "billing_syncs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "COMPLETED",
                "FAILED",
                name="billing_sync_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entries_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("entries_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_syncs_provider", "billing_syncs", ["provider"])
    op.create_index("ix_billing_syncs_status", "billing_syncs", ["status"])
    op.create_index("ix_billing_syncs_started_at", "billing_syncs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_billing_syncs_started_at", table_name="billing_syncs")
    op.drop_index("ix_billing_syncs_status", table_name="billing_syncs")
    op.drop_index("ix_billing_syncs_provider", table_name="billing_syncs")
    op.drop_table("billing_syncs")

    op.drop_index("ix_provider_cost_entries_model", table_name="provider_cost_entries")
    op.drop_index("ix_provider_cost_entries_period_end", table_name="provider_cost_entries")
    op.drop_index("ix_provider_cost_entries_period_start", table_name="provider_cost_entries")
    op.drop_index("ix_provider_cost_entries_source", table_name="provider_cost_entries")
    op.drop_index("ix_provider_cost_entries_provider", table_name="provider_cost_entries")
    op.drop_table("provider_cost_entries")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_index("ix_agent_runs_provider")
        batch_op.drop_column("reasoning_tokens")
        batch_op.drop_column("cached_input_tokens")
        batch_op.drop_column("provider")
