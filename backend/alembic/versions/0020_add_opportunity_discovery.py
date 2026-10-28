"""add opportunity discovery

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "founder_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("industries", sa.JSON(), nullable=False),
        sa.Column("available_capital", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("hours_per_week", sa.Integer(), nullable=False),
        sa.Column("target_monthly_revenue", sa.Numeric(14, 2), nullable=False),
        sa.Column("revenue_horizon_days", sa.Integer(), nullable=False),
        sa.Column("preferred_business_models", sa.JSON(), nullable=False),
        sa.Column("preferred_markets", sa.JSON(), nullable=False),
        sa.Column("distribution_assets", sa.JSON(), nullable=False),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("risk_tolerance", sa.String(6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("risk_tolerance IN ('LOW', 'MEDIUM', 'HIGH')", name="ck_founder_risk_tolerance"),
    )
    op.create_table(
        "discovery_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("founder_profile_id", sa.String(36), nullable=False),
        sa.Column("agent_profile_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("geography", sa.String(120), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_ai_budget", sa.Numeric(12, 6), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("candidate_target", sa.Integer(), nullable=False),
        sa.Column("finalist_target", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("current_stage", sa.String(80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["founder_profile_id"], ["founder_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_profile_id"], ["agent_profiles.id"], ondelete="SET NULL"),
        sa.CheckConstraint("candidate_target >= 3 AND candidate_target <= 20", name="ck_discovery_candidate_target"),
        sa.CheckConstraint("finalist_target >= 1 AND finalist_target <= 5", name="ck_discovery_finalist_target"),
        sa.CheckConstraint("total_cost >= 0 AND max_ai_budget > 0", name="ck_discovery_budget"),
        sa.CheckConstraint("status IN ('DRAFT', 'RUNNING', 'COMPLETED', 'BUDGET_STOPPED', 'FAILED', 'CANCELLED')", name="ck_discovery_status"),
    )
    for column in ("founder_profile_id", "agent_profile_id", "status", "created_at"):
        op.create_index(f"ix_discovery_campaigns_{column}", "discovery_campaigns", [column])
    op.create_table(
        "opportunity_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_title", sa.String(300), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("pain_statement", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(300), nullable=False),
        sa.Column("evidence_type", sa.String(80), nullable=False),
        sa.Column("observed_signal", sa.Text(), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("willingness_to_pay", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["discovery_campaigns.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_id", "sequence", name="uq_opportunity_signal_sequence"),
    )
    op.create_index("ix_opportunity_signals_campaign_id", "opportunity_signals", ["campaign_id"])
    op.create_table(
        "opportunity_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("target_customer", sa.Text(), nullable=False),
        sa.Column("solution", sa.Text(), nullable=False),
        sa.Column("business_model", sa.Text(), nullable=False),
        sa.Column("acquisition_channel", sa.Text(), nullable=False),
        sa.Column("pricing_hypothesis", sa.Text(), nullable=False),
        sa.Column("first_revenue_path", sa.Text(), nullable=False),
        sa.Column("founder_fit_reason", sa.Text(), nullable=False),
        sa.Column("signal_codes", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("research", sa.JSON(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("preliminary_score", sa.Float(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["discovery_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('GENERATED', 'SHORTLISTED', 'FINALIST', 'REJECTED', 'SELECTED')", name="ck_opportunity_status"),
    )
    for column in ("campaign_id", "project_id", "status", "created_at"):
        op.create_index(f"ix_opportunity_candidates_{column}", "opportunity_candidates", [column])
    op.create_table(
        "discovery_agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("agent", sa.String(24), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("web_search_calls", sa.Integer(), nullable=False),
        sa.Column("tool_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("web_sources", sa.JSON(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("execution_time", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["discovery_campaigns.id"], ondelete="CASCADE"),
        sa.CheckConstraint("agent IN ('OPPORTUNITY_SCOUT', 'IDEA_GENERATOR', 'OPPORTUNITY_RESEARCHER', 'PORTFOLIO_JUDGE')", name="ck_discovery_agent_type"),
    )
    for column in ("campaign_id", "agent", "created_at"):
        op.create_index(f"ix_discovery_agent_runs_{column}", "discovery_agent_runs", [column])


def downgrade() -> None:
    op.drop_table("discovery_agent_runs")
    op.drop_table("opportunity_candidates")
    op.drop_table("opportunity_signals")
    op.drop_table("discovery_campaigns")
    op.drop_table("founder_profiles")
