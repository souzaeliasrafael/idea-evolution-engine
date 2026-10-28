from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    CommercialValidationStatus,
    DiscoveryAgentType,
    DiscoveryCampaignStatus,
    DiscoveryMemoryMode,
    OpportunityFeedbackStatus,
    OpportunityCustomerType,
    OpportunityRevenuePattern,
    OpportunityStatus,
    RiskTolerance,
)


ShortText = Annotated[str, Field(min_length=1, max_length=300)]
Paragraph = Annotated[str, Field(min_length=1, max_length=1500)]
StringList = Annotated[list[ShortText], Field(max_length=20)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class FounderProfileCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    skills: StringList = []
    industries: StringList = []
    available_capital: Money = Decimal("0")
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "BRL"
    hours_per_week: int = Field(default=20, ge=1, le=168)
    target_monthly_revenue: Money = Decimal("10000")
    revenue_horizon_days: int = Field(default=90, ge=7, le=1825)
    preferred_business_models: StringList = []
    preferred_markets: StringList = []
    distribution_assets: StringList = []
    technologies: StringList = []
    exclusions: StringList = []
    risk_tolerance: RiskTolerance = RiskTolerance.MEDIUM


class FounderProfileUpdate(FounderProfileCreate):
    pass


class FounderProfileRead(FounderProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class DiscoveryHardConstraints(BaseModel):
    """Machine-enforced boundaries for a discovery campaign."""

    model_config = ConfigDict(extra="forbid")

    customer_type: OpportunityCustomerType = OpportunityCustomerType.B2C
    digital_only: bool = True
    self_service_only: bool = True
    min_automation_percent: int = Field(default=90, ge=0, le=100)
    max_mvp_days: int = Field(default=30, ge=1, le=365)
    exclude_recurring_human_service: bool = True
    exclude_regulated_advice: bool = True
    exclude_two_sided_marketplaces: bool = True
    require_recurring_or_repeat_revenue: bool = True
    require_reachable_channel: bool = True
    min_demand_sources: int = Field(default=3, ge=1, le=10)
    min_paid_competitors: int = Field(default=2, ge=0, le=10)
    min_market_reality_score: int = Field(default=55, ge=0, le=100)


class DiscoveryCampaignCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    founder_profile_id: UUID
    agent_profile_id: UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)]
    brief: Annotated[str, Field(max_length=5000)] = ""
    geography: Annotated[str, Field(min_length=1, max_length=120)] = "Brasil"
    language: Annotated[str, Field(min_length=2, max_length=20)] = "pt-BR"
    memory_mode: DiscoveryMemoryMode = DiscoveryMemoryMode.BALANCED
    hard_constraints: DiscoveryHardConstraints = Field(default_factory=DiscoveryHardConstraints)
    max_ai_budget: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=6)]
    candidate_target: int = Field(default=5, ge=3, le=5)
    finalist_target: int = Field(default=2, ge=1, le=3)


class DiscoveryCampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    founder_profile_id: UUID
    agent_profile_id: UUID | None
    name: str
    brief: str
    geography: str
    language: str
    memory_mode: DiscoveryMemoryMode
    hard_constraints: DiscoveryHardConstraints
    status: DiscoveryCampaignStatus
    max_ai_budget: Decimal
    total_cost: Decimal
    candidate_target: int
    finalist_target: int
    cancellation_requested: bool
    current_stage: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OpportunitySignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    sequence: int
    source_title: str
    source_url: str
    pain_statement: str
    audience: str
    evidence_type: str
    observed_signal: str
    commercial_signal: str
    commercial_strength: int
    strength: int
    frequency: int
    willingness_to_pay: int
    created_at: datetime


class OpportunityCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    title: str
    problem: str
    target_customer: str
    solution: str
    business_model: str
    acquisition_channel: str
    pricing_hypothesis: str
    first_revenue_path: str
    founder_fit_reason: str
    signal_codes: list[str]
    inspired_by_candidate_ids: list[str]
    risks: list[str]
    business_case: dict[str, object]
    hard_constraint_passed: bool
    disqualification_reasons: list[str]
    research: dict[str, object]
    scores: dict[str, int]
    preliminary_score: float
    market_reality_score: float | None
    market_gate_passed: bool
    overall_score: float | None
    confidence: float | None
    rank: int | None
    status: OpportunityStatus
    user_feedback: OpportunityFeedbackStatus
    feedback_tags: list[str]
    feedback_note: str | None
    feedback_at: datetime | None
    validation_status: CommercialValidationStatus
    validation_result: dict[str, object]
    created_at: datetime


class OpportunityFeedbackUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_feedback: OpportunityFeedbackStatus
    feedback_tags: Annotated[list[ShortText], Field(max_length=10)] = []
    feedback_note: Annotated[str, Field(max_length=2000)] | None = None


class DiscoveryAgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent: DiscoveryAgentType
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    web_search_calls: int
    tool_cost: Decimal
    web_sources: list[dict[str, object]]
    estimated_cost: Decimal
    execution_time: float
    error: str | None
    created_at: datetime


class DiscoveryPromptUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: Annotated[str, Field(min_length=20, max_length=20_000)]


class DiscoveryPromptRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: DiscoveryAgentType
    content: str
    version: str
    customized: bool
    default_content: str
    default_version: str
    updated_at: datetime | None


class DiscoveryPromptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent: DiscoveryAgentType
    version: int
    content: str
    is_active: bool
    created_at: datetime


class OpportunityPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_ai_budget: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6)] | None = None
    allow_manual_override: bool = False


class DiscoveryHandoffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    campaign_id: UUID
    candidate_id: UUID
    schema_version: int
    snapshot: dict[str, object]
    created_at: datetime


# Typed outputs used by the four bounded discovery agents.
class ScoutSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_title: ShortText
    source_url: Annotated[str, Field(min_length=8, max_length=2000, pattern=r"^https?://")]
    pain_statement: Paragraph
    audience: ShortText
    evidence_type: Annotated[str, Field(min_length=1, max_length=80)]
    observed_signal: Paragraph
    commercial_signal: Paragraph
    commercial_strength: int = Field(ge=1, le=5)
    strength: int = Field(ge=1, le=5)
    frequency: int = Field(ge=1, le=5)
    willingness_to_pay: int = Field(ge=1, le=5)


class OpportunityScoutOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: Annotated[list[ScoutSignal], Field(min_length=3, max_length=12)]
    search_summary: Annotated[str, Field(min_length=1, max_length=1200)]


class OpportunityBusinessCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_type: OpportunityCustomerType
    digital_product: bool
    self_service: bool
    automation_percent: int = Field(ge=0, le=100)
    mvp_days: int = Field(ge=1, le=365)
    recurring_human_service: bool
    regulated_advice: bool
    two_sided_marketplace: bool
    revenue_pattern: OpportunityRevenuePattern


class GeneratedOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=240)]
    problem: Paragraph
    target_customer: Paragraph
    solution: Paragraph
    business_model: Paragraph
    acquisition_channel: Paragraph
    pricing_hypothesis: Paragraph
    first_revenue_path: Paragraph
    founder_fit_reason: Paragraph
    signal_codes: Annotated[list[str], Field(min_length=1, max_length=8)]
    inspired_by_candidate_ids: Annotated[list[str], Field(max_length=3)]
    risks: Annotated[list[ShortText], Field(max_length=6)]
    business_case: OpportunityBusinessCase


class OpportunityGeneratorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunities: Annotated[list[GeneratedOpportunity], Field(min_length=3, max_length=5)]


class ResearchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: Paragraph
    source_url: Annotated[str, Field(min_length=8, max_length=2000, pattern=r"^https?://")]
    evidence_kind: Annotated[str, Field(min_length=1, max_length=80)]
    supports_purchase_behavior: bool


class OpportunityResearchAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=36)
    demand_evidence: Annotated[list[ResearchEvidence], Field(max_length=5)]
    competitor_evidence: Annotated[list[ResearchEvidence], Field(max_length=5)]
    objections: Annotated[list[ShortText], Field(max_length=5)]
    buyer: Paragraph
    purchase_event: Paragraph
    current_spend: Paragraph
    purchase_frequency: Paragraph
    reachable_acquisition_channel: Paragraph
    gross_margin_estimate: Paragraph
    cac_ceiling: Paragraph
    paid_competitor_count: int = Field(ge=0, le=100)
    direct_purchase_evidence: bool
    demand_signal_score: int = Field(ge=0, le=100)
    willingness_to_pay_score: int = Field(ge=0, le=100)
    paid_competitor_score: int = Field(ge=0, le=100)
    channel_score: int = Field(ge=0, le=100)
    recurrence_score: int = Field(ge=0, le=100)
    margin_score: int = Field(ge=0, le=100)
    evidence_quality_score: int = Field(ge=0, le=100)
    recommended_validation: Paragraph
    confidence: float = Field(ge=0, le=1)


class OpportunityResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyses: Annotated[list[OpportunityResearchAnalysis], Field(min_length=1, max_length=10)]


class PortfolioEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=36)
    rationale: Paragraph
    pain_severity: int = Field(ge=0, le=100)
    willingness_to_pay: int = Field(ge=0, le=100)
    reachability: int = Field(ge=0, le=100)
    founder_fit: int = Field(ge=0, le=100)
    economics: int = Field(ge=0, le=100)
    speed_to_revenue: int = Field(ge=0, le=100)
    differentiation: int = Field(ge=0, le=100)
    feasibility: int = Field(ge=0, le=100)
    regulatory_safety: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    matched_rejection_tags: Annotated[list[ShortText], Field(max_length=5)]
    validation_plan: Annotated[list[ShortText], Field(min_length=1, max_length=5)]


class PortfolioJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluations: Annotated[list[PortfolioEvaluation], Field(min_length=1, max_length=10)]
    portfolio_summary: Annotated[str, Field(min_length=1, max_length=1500)]


class CommercialValidationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: CommercialValidationStatus
    channel: Annotated[str, Field(min_length=1, max_length=300)]
    hypothesis: Annotated[str, Field(min_length=1, max_length=1000)]
    visits: int = Field(default=0, ge=0)
    leads: int = Field(default=0, ge=0)
    preorders: int = Field(default=0, ge=0)
    paying_customers: int = Field(default=0, ge=0)
    revenue: Money = Decimal("0")
    spend: Money = Decimal("0")
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "BRL"
    notes: Annotated[str, Field(max_length=2000)] = ""
