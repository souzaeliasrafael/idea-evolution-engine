from __future__ import annotations

from datetime import UTC, date as DateValue, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.enums import (
    AgentType,
    BillingCostSource,
    BillingSyncStatus,
    CriticismSeverity,
    CommercialValidationStatus,
    DecisionType,
    DiscoveryAgentType,
    DiscoveryCampaignStatus,
    DiscoveryMemoryMode,
    DevelopmentBlueprintStatus,
    EpistemicClassification,
    EvidenceDirection,
    EvidenceOrigin,
    ExperimentOutcome,
    ExperimentReassessmentStatus,
    ExperimentStatus,
    HumanReviewAction,
    HumanReviewStatus,
    HypothesisOrigin,
    HypothesisStatus,
    ProjectStatus,
    OpportunityStatus,
    OpportunityFeedbackStatus,
    RiskTolerance,
    RoundStatus,
    WorkflowExecutionStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class FounderProfile(Base):
    __tablename__ = "founder_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    industries: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    available_capital: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    target_monthly_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    revenue_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_business_models: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_markets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    distribution_assets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exclusions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_tolerance: Mapped[RiskTolerance] = mapped_column(
        SqlEnum(RiskTolerance, name="risk_tolerance", native_enum=False, create_constraint=True),
        default=RiskTolerance.MEDIUM,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DiscoveryCampaign(Base):
    __tablename__ = "discovery_campaigns"
    __table_args__ = (
        CheckConstraint("candidate_target >= 3 AND candidate_target <= 20", name="ck_discovery_candidate_target"),
        CheckConstraint("finalist_target >= 1 AND finalist_target <= 5", name="ck_discovery_finalist_target"),
        CheckConstraint("total_cost >= 0 AND max_ai_budget > 0", name="ck_discovery_budget"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    founder_profile_id: Mapped[str] = mapped_column(ForeignKey("founder_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    geography: Mapped[str] = mapped_column(String(120), default="Brasil", nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="pt-BR", nullable=False)
    memory_mode: Mapped[DiscoveryMemoryMode] = mapped_column(
        SqlEnum(DiscoveryMemoryMode, name="discovery_memory_mode", native_enum=False, create_constraint=True),
        default=DiscoveryMemoryMode.BALANCED,
        server_default=DiscoveryMemoryMode.BALANCED.value,
        nullable=False,
    )
    status: Mapped[DiscoveryCampaignStatus] = mapped_column(
        SqlEnum(DiscoveryCampaignStatus, name="discovery_campaign_status", native_enum=False, create_constraint=True),
        default=DiscoveryCampaignStatus.DRAFT,
        nullable=False,
        index=True,
    )
    max_ai_budget: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    hard_constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    candidate_target: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    finalist_target: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class OpportunitySignal(Base):
    __tablename__ = "opportunity_signals"
    __table_args__ = (UniqueConstraint("campaign_id", "sequence", name="uq_opportunity_signal_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("discovery_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    pain_statement: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(300), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    observed_signal: Mapped[str] = mapped_column(Text, nullable=False)
    commercial_signal: Mapped[str] = mapped_column(Text, default="Não informado", nullable=False)
    commercial_strength: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    willingness_to_pay: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    @property
    def code(self) -> str:
        return f"S{self.sequence:03d}"


class OpportunityCandidate(Base):
    __tablename__ = "opportunity_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("discovery_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    target_customer: Mapped[str] = mapped_column(Text, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    business_model: Mapped[str] = mapped_column(Text, nullable=False)
    acquisition_channel: Mapped[str] = mapped_column(Text, nullable=False)
    pricing_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    first_revenue_path: Mapped[str] = mapped_column(Text, nullable=False)
    founder_fit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    signal_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    inspired_by_candidate_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    business_case: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    hard_constraint_passed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disqualification_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    research: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scores: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    preliminary_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    market_reality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_gate_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[OpportunityStatus] = mapped_column(
        SqlEnum(OpportunityStatus, name="opportunity_status", native_enum=False, create_constraint=True),
        default=OpportunityStatus.GENERATED,
        nullable=False,
        index=True,
    )
    user_feedback: Mapped[OpportunityFeedbackStatus] = mapped_column(
        SqlEnum(OpportunityFeedbackStatus, name="opportunity_feedback_status", native_enum=False, create_constraint=True),
        default=OpportunityFeedbackStatus.PENDING,
        server_default=OpportunityFeedbackStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    feedback_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_status: Mapped[CommercialValidationStatus] = mapped_column(
        SqlEnum(
            CommercialValidationStatus,
            name="commercial_validation_status",
            native_enum=False,
            create_constraint=True,
        ),
        default=CommercialValidationStatus.UNTESTED,
        server_default=CommercialValidationStatus.UNTESTED.value,
        nullable=False,
    )
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class DiscoveryHandoff(Base):
    """Immutable discovery snapshot used to initialize a promoted project."""

    __tablename__ = "discovery_handoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_campaigns.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_candidates.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DiscoveryAgentRun(Base):
    __tablename__ = "discovery_agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("discovery_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    agent: Mapped[DiscoveryAgentType] = mapped_column(
        SqlEnum(DiscoveryAgentType, name="discovery_agent_type", native_enum=False, create_constraint=True),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    web_search_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    web_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    execution_time: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_idea: Mapped[str] = mapped_column(Text, nullable=False)
    agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_plan: Mapped[dict[str, int]] = mapped_column(
        JSON,
        default=lambda: {"builder": 1, "researcher": 1, "critic": 1},
        nullable=False,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        SqlEnum(
            ProjectStatus,
            name="project_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ProjectStatus.DRAFT,
        server_default=ProjectStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    max_ai_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    next_round_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    stagnation_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @property
    def remaining_ai_budget(self) -> Decimal | None:
        if self.max_ai_budget is None:
            return None
        return max(Decimal("0"), self.max_ai_budget - self.total_cost)

    @property
    def budget_exhausted(self) -> bool:
        return (
            self.max_ai_budget is not None
            and self.total_cost >= self.max_ai_budget
        )


class ImmutableIdeaVersionError(RuntimeError):
    """Raised when application code tries to mutate an immutable idea version."""


class IdeaVersion(Base):
    __tablename__ = "idea_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_idea_versions_project_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="RESTRICT"), nullable=True
    )
    reason_for_change: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[AgentType] = mapped_column(
        SqlEnum(
            AgentType,
            name="agent_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    changes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    concept: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


@event.listens_for(IdeaVersion, "before_update")
def prevent_idea_version_update(*_: object) -> None:
    raise ImmutableIdeaVersionError("Idea versions cannot be updated")


@event.listens_for(IdeaVersion, "before_delete")
def prevent_idea_version_delete(*_: object) -> None:
    raise ImmutableIdeaVersionError("Idea versions cannot be deleted")


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (
        UniqueConstraint("project_id", "round_number", name="uq_round_project_number"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RoundStatus] = mapped_column(
        SqlEnum(
            RoundStatus,
            name="round_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    starting_version_id: Mapped[str] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="RESTRICT"), nullable=False
    )
    resulting_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[DecisionType | None] = mapped_column(
        SqlEnum(
            DecisionType,
            name="round_decision_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_limit_reached: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    stagnation_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_id: Mapped[str | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent: Mapped[AgentType] = mapped_column(
        SqlEnum(
            AgentType,
            name="agent_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(100), default="unknown", server_default="unknown", nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reasoning_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    web_search_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    tool_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    web_sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), nullable=False
    )
    execution_time: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class WorkflowExecution(Base):
    """Durable coordination record for one project's active workflow."""

    __tablename__ = "workflow_executions"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[WorkflowExecutionStatus] = mapped_column(
        SqlEnum(
            WorkflowExecutionStatus,
            name="workflow_execution_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=WorkflowExecutionStatus.IDLE,
        server_default=WorkflowExecutionStatus.IDLE.value,
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    current_agent: Mapped[AgentType | None] = mapped_column(
        SqlEnum(
            AgentType,
            name="workflow_current_agent_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    workflow_stage: Mapped[str | None] = mapped_column(String(160), nullable=True)
    current_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    round_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DevelopmentBlueprint(Base):
    __tablename__ = "development_blueprints"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_development_blueprint_project_version"
        ),
        CheckConstraint(
            "architecture_alternatives >= 1 AND architecture_alternatives <= 3",
            name="ck_development_blueprint_alternatives",
        ),
        CheckConstraint(
            "estimated_cost >= 0", name="ck_development_blueprint_cost"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DevelopmentBlueprintStatus] = mapped_column(
        SqlEnum(
            DevelopmentBlueprintStatus,
            name="development_blueprint_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=DevelopmentBlueprintStatus.RUNNING,
        server_default=DevelopmentBlueprintStatus.RUNNING.value,
        nullable=False,
        index=True,
    )
    architecture_alternatives: Mapped[int] = mapped_column(Integer, nullable=False)
    user_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_ai_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    product_definition: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    architecture_options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    technical_review: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    final_blueprint: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    agent_run_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProviderCostEntry(Base):
    __tablename__ = "provider_cost_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    external_reference: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[BillingCostSource] = mapped_column(
        SqlEnum(
            BillingCostSource,
            name="billing_cost_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    line_item: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_project_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_api_key_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class BillingSync(Base):
    __tablename__ = "billing_syncs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[BillingSyncStatus] = mapped_column(
        SqlEnum(
            BillingSyncStatus,
            name="billing_sync_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entries_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entries_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "sequence", name="uq_hypothesis_project_sequence"
        ),
        UniqueConstraint(
            "project_id", "statement", name="uq_hypothesis_project_statement"
        ),
        CheckConstraint("impact >= 1 AND impact <= 10", name="ck_hypothesis_impact"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_hypothesis_confidence",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[HypothesisStatus] = mapped_column(
        SqlEnum(
            HypothesisStatus,
            name="hypothesis_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    epistemic_classification: Mapped[EpistemicClassification] = mapped_column(
        SqlEnum(
            EpistemicClassification,
            name="epistemic_classification",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    origin: Mapped[HypothesisOrigin] = mapped_column(
        SqlEnum(
            HypothesisOrigin,
            name="hypothesis_origin",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    source_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @property
    def code(self) -> str:
        return f"H{self.sequence:03d}"

    @property
    def priority(self) -> float:
        return round(self.impact * (1 - self.confidence), 4)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_evidence_project_sequence"),
        CheckConstraint("strength >= 0 AND strength <= 5", name="ck_evidence_strength"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[EvidenceDirection] = mapped_column(
        SqlEnum(
            EvidenceDirection,
            name="evidence_direction",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    epistemic_classification: Mapped[EpistemicClassification] = mapped_column(
        SqlEnum(
            EpistemicClassification,
            name="evidence_epistemic_classification",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date: Mapped[DateValue | None] = mapped_column(Date, nullable=True)
    origin: Mapped[EvidenceOrigin] = mapped_column(
        SqlEnum(
            EvidenceOrigin,
            name="evidence_origin",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    @property
    def code(self) -> str:
        return f"E{self.sequence:03d}"


class Criticism(Base):
    __tablename__ = "criticisms"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idea_version_id: Mapped[str] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[CriticismSeverity] = mapped_column(
        SqlEnum(
            CriticismSeverity,
            name="criticism_severity",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    affected_hypotheses: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_needed: Mapped[str] = mapped_column(Text, nullable=False)
    condition_that_refutes_criticism: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class ProjectScore(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idea_version_id: Mapped[str] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[DecisionType] = mapped_column(
        SqlEnum(
            DecisionType,
            name="decision_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    from_version_id: Mapped[str] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="CASCADE"), nullable=False
    )
    to_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="SET NULL"), nullable=True
    )
    score_id: Mapped[str] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    critical_blockers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    most_important_unknowns: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    next_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    human_review_status: Mapped[HumanReviewStatus] = mapped_column(
        SqlEnum(
            HumanReviewStatus,
            name="human_review_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=HumanReviewStatus.NOT_REQUIRED,
        server_default=HumanReviewStatus.NOT_REQUIRED.value,
        nullable=False,
        index=True,
    )
    human_action: Mapped[HumanReviewAction | None] = mapped_column(
        SqlEnum(
            HumanReviewAction,
            name="human_review_action",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class JudgeChatTurn(Base):
    __tablename__ = "judge_chat_turns"
    __table_args__ = (
        CheckConstraint(
            "input_mode IN ('TEXT', 'VOICE')",
            name="ck_judge_chat_turn_input_mode",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'NO_DECISION', 'CANCELLED', 'BUDGET_STOPPED', 'FAILED')",
            name="ck_judge_chat_turn_status",
        ),
        CheckConstraint(
            "requested_rounds >= 1", name="ck_judge_chat_turn_requested_rounds"
        ),
        CheckConstraint(
            "cost_before >= 0 AND cost_after >= 0",
            name="ck_judge_chat_turn_costs",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    input_mode: Mapped[str] = mapped_column(
        String(10), default="TEXT", server_default="TEXT", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_rounds: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    judge_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_before: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    cost_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ImprovementPlan(Base):
    __tablename__ = "improvement_plans"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_improvement_plan_project_version"
        ),
        CheckConstraint(
            "source_score >= 0 AND source_score <= 100",
            name="ck_improvement_plan_score",
        ),
        CheckConstraint(
            "source_confidence >= 0 AND source_confidence <= 1",
            name="ck_improvement_plan_confidence",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_id: Mapped[str | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idea_version_id: Mapped[str] = mapped_column(
        ForeignKey("idea_versions.id", ondelete="CASCADE"), nullable=False
    )
    score_id: Mapped[str] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_score: Mapped[int] = mapped_column(Integer, nullable=False)
    source_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("estimated_cost >= 0", name="ck_experiment_estimated_cost"),
        CheckConstraint("actual_cost >= 0", name="ck_experiment_actual_cost"),
        CheckConstraint(
            "evidence_quality IS NULL OR (evidence_quality >= 0 AND evidence_quality <= 5)",
            name="ck_experiment_evidence_quality",
        ),
        CheckConstraint(
            "sample_size IS NULL OR sample_size > 0",
            name="ck_experiment_sample_size",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    experiment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    success_metric: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_threshold: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    actual_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0", nullable=False
    )
    status: Mapped[ExperimentStatus] = mapped_column(
        SqlEnum(
            ExperimentStatus,
            name="experiment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ExperimentStatus.PLANNED,
        server_default=ExperimentStatus.PLANNED.value,
        nullable=False,
        index=True,
    )
    outcome: Mapped[ExperimentOutcome | None] = mapped_column(
        SqlEnum(
            ExperimentOutcome,
            name="experiment_outcome",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    methodology: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    evidence_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affected_criteria: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    reassessment_status: Mapped[ExperimentReassessmentStatus] = mapped_column(
        SqlEnum(
            ExperimentReassessmentStatus,
            name="experiment_reassessment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ExperimentReassessmentStatus.NOT_REQUESTED,
        server_default=ExperimentReassessmentStatus.NOT_REQUESTED.value,
        nullable=False,
        index=True,
    )
    previous_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reassessed_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reassessed_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reassessment_score_id: Mapped[str | None] = mapped_column(
        ForeignKey("scores.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    reassessment_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    reassessment_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agents: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AgentPromptVersion(Base):
    __tablename__ = "agent_prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "agent", "version", name="uq_agent_prompt_versions_agent_version"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    agent: Mapped[AgentType] = mapped_column(
        SqlEnum(
            AgentType,
            name="agent_prompt_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class DiscoveryPromptVersion(Base):
    __tablename__ = "discovery_prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent", "version", name="uq_discovery_prompt_agent_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent: Mapped[DiscoveryAgentType] = mapped_column(
        SqlEnum(DiscoveryAgentType, name="discovery_prompt_type", native_enum=False, create_constraint=True),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
