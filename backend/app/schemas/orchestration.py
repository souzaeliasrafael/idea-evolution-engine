from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    AgentType,
    DecisionType,
    OrchestratorStopReason,
    ProjectStatus,
    RoundStatus,
    WorkflowExecutionStatus,
)
from app.orchestration.rules import DEFAULT_ROUNDS_PER_RUN


class OrchestratorRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_rounds: int = Field(default=DEFAULT_ROUNDS_PER_RUN, ge=1)


class RoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    round_number: int = Field(ge=1)
    status: RoundStatus
    starting_version_id: UUID
    resulting_version_id: UUID | None
    decision: DecisionType | None
    score: int | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    budget_limit_reached: bool
    stagnation_detected: bool
    error: str | None
    human_context: str | None
    started_at: datetime
    completed_at: datetime | None


class OrchestratorRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_status: ProjectStatus
    rounds: list[RoundRead]
    final_decision: DecisionType | None
    final_score: int | None = Field(default=None, ge=0, le=100)
    final_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    stop_reason: OrchestratorStopReason


class WorkflowProgressRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    status: WorkflowExecutionStatus
    current_agent: AgentType | None = None
    workflow_stage: str | None = None
    current_round: int | None = Field(default=None, ge=1)
    round_position: int | None = Field(default=None, ge=1)
    requested_rounds: int | None = Field(default=None, ge=1)
    agent_iteration: int | None = Field(default=None, ge=1)
    agent_iterations: int | None = Field(default=None, ge=1)
    started_at: datetime | None = None
    updated_at: datetime | None = None
