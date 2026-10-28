from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    DecisionType,
    HumanReviewAction,
    HumanReviewStatus,
    ScoreCriterion,
)


NonBlankText = Annotated[str, Field(min_length=1)]


class CriterionAssessment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    criterion: ScoreCriterion
    rating: int = Field(ge=0, le=5)
    rationale: NonBlankText
    evidence_ids: list[NonBlankText]


class JudgeAssessment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    decision: DecisionType
    criteria: list[CriterionAssessment]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: NonBlankText
    critical_blockers: list[NonBlankText]
    most_important_unknowns: list[NonBlankText]
    next_actions: list[NonBlankText]


class ScoreBreakdownItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    criterion: ScoreCriterion
    rating: int = Field(ge=0, le=5)
    weight: int = Field(ge=0)
    weighted_score: int = Field(ge=0)
    rationale: str
    evidence_ids: list[str]


class ScoreCalculation(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_score: int = Field(ge=0, le=100)
    breakdown: list[ScoreBreakdownItem]


class JudgeOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: DecisionType
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str
    critical_blockers: list[str]
    most_important_unknowns: list[str]
    next_actions: list[str]
    score_breakdown: list[ScoreBreakdownItem]
    stagnation_detected: bool


class ScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    idea_version_id: UUID
    agent_run_id: UUID
    total_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    breakdown: list[ScoreBreakdownItem]
    created_at: datetime


class DecisionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    round_number: int | None
    decision: DecisionType
    reason: str
    from_version_id: UUID
    to_version_id: UUID | None
    score_id: UUID
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    critical_blockers: list[str]
    most_important_unknowns: list[str]
    next_actions: list[str]
    human_review_status: HumanReviewStatus
    human_action: HumanReviewAction | None
    human_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
