from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AgentType
from app.schemas.experiments import ExperimentRead
from app.schemas.idea import IdeaVersionRead
from app.schemas.judgment import DecisionRead, ScoreRead
from app.schemas.knowledge import EvidenceRead, HypothesisRead
from app.schemas.orchestration import RoundRead
from app.schemas.project import ProjectRead
from app.schemas.timeline import TimelineItemRead
from app.schemas.evaluation import CriticismRead
from app.schemas.development import DevelopmentBlueprintRead
from app.schemas.improvement import ImprovementPlanRead
from app.schemas.judge_chat import JudgeChatTurnRead


class AgentMetricRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentType
    provider: str
    model: str
    runs: int = Field(ge=0)
    successful_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    estimated_cost: Decimal = Field(ge=0)
    average_execution_time: float = Field(ge=0)


class ProjectMetricsRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    total_runs: int = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_estimated_cost: Decimal = Field(ge=0)
    by_agent: list[AgentMetricRead]


class RoundEfficiencyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    round_number: int = Field(ge=1)
    status: str
    calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    input_payload_characters: int = Field(ge=0)
    largest_input_payload_characters: int = Field(ge=0)
    estimated_cost: Decimal = Field(ge=0)
    score: int | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    score_delta: int | None = None
    confidence_delta: float | None = None
    cost_per_score_point: Decimal | None = Field(default=None, ge=0)


class ProjectEfficiencyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    rounds: list[RoundEfficiencyRead]
    total_round_cost: Decimal = Field(ge=0)
    recommendation: str
    recommendation_reason: str


class ProjectReportRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    project: ProjectRead
    current_version: IdeaVersionRead | None
    versions: list[IdeaVersionRead]
    scores: list[ScoreRead]
    decisions: list[DecisionRead]
    judge_chat_turns: list[JudgeChatTurnRead]
    rounds: list[RoundRead]
    hypotheses: list[HypothesisRead]
    evidence: list[EvidenceRead]
    criticisms: list[CriticismRead]
    experiments: list[ExperimentRead]
    improvement_plans: list[ImprovementPlanRead]
    development_blueprints: list[DevelopmentBlueprintRead]
    timeline: list[TimelineItemRead]
    metrics: ProjectMetricsRead


class ProjectBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    exported_at: datetime
    data: dict[str, list[dict[str, Any]]]


class ProviderDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentType
    provider: str
    model: str
    input_cost_per_million: Decimal = Field(ge=0)
    cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    output_cost_per_million: Decimal = Field(ge=0)
    credential_configured: bool
    pricing_configured: bool


class SystemConfigRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str
    app_env: str
    max_rounds: int
    max_attempts: int
    max_output_tokens: int
    builder_max_output_tokens: int
    adaptive_agent_depth_enabled: bool
    adaptive_depth_score_threshold: int = Field(ge=0, le=100)
    adaptive_depth_confidence_threshold: float = Field(ge=0, le=1)
    research_web_enabled: bool
    research_web_max_calls: int = Field(ge=1, le=10)
    research_web_context_size: str
    web_search_cost_per_call: Decimal = Field(ge=0)
    providers: list[ProviderDiagnostic]


class HealthRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    version: str
    database: str
