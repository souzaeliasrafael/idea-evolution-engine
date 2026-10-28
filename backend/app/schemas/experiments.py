from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ExperimentOutcome,
    ExperimentReassessmentStatus,
    ExperimentStatus,
    ScoreCriterion,
)


NonBlankText = Annotated[str, Field(min_length=1)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6)]


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    hypothesis_id: UUID | None = None
    experiment_type: Annotated[str, Field(min_length=1, max_length=100)]
    description: NonBlankText
    success_metric: NonBlankText | None = None
    success_threshold: NonBlankText | None = None
    estimated_cost: Money = Decimal("0")


class ExperimentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    experiment_type: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    description: NonBlankText | None = None
    success_metric: NonBlankText | None = None
    success_threshold: NonBlankText | None = None
    estimated_cost: Money | None = None
    actual_cost: Money | None = None
    status: ExperimentStatus | None = None
    outcome: ExperimentOutcome | None = None
    result_summary: NonBlankText | None = None
    observed_value: NonBlankText | None = None
    sample_size: int | None = Field(default=None, ge=1)
    methodology: NonBlankText | None = None
    limitations: NonBlankText | None = None


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    decision_id: UUID | None
    hypothesis_id: UUID | None
    experiment_type: str
    description: str
    success_metric: str | None
    success_threshold: str | None
    estimated_cost: Decimal
    actual_cost: Decimal
    status: ExperimentStatus
    outcome: ExperimentOutcome | None
    result_summary: str | None
    observed_value: str | None
    sample_size: int | None
    methodology: str | None
    limitations: str | None
    evidence_id: UUID | None
    evidence_quality: int | None = Field(default=None, ge=0, le=5)
    affected_criteria: list[ScoreCriterion]
    reassessment_status: ExperimentReassessmentStatus
    previous_score: int | None = Field(default=None, ge=0, le=100)
    previous_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reassessed_score: int | None = Field(default=None, ge=0, le=100)
    reassessed_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reassessment_score_id: UUID | None
    reassessment_decision_id: UUID | None
    reassessment_error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
