from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ImprovementCauseType,
    ImprovementEffort,
    ScoreCriterion,
)


ShortText = Annotated[str, Field(min_length=1, max_length=1200)]
EvidenceCode = Annotated[str, Field(pattern=r"^E[0-9]{3,}$")]


class WeaknessAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    criterion: ScoreCriterion
    current_rating: int = Field(ge=0, le=5)
    cause_type: ImprovementCauseType
    diagnosis: ShortText
    consequence: ShortText
    confidence_limit: ShortText
    evidence_ids: list[EvidenceCode] = Field(max_length=20)


class ImprovementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: ShortText
    target_criteria: list[ScoreCriterion] = Field(min_length=1, max_length=6)
    rationale: ShortText
    feasibility: int = Field(ge=1, le=5)
    expected_impact: int = Field(ge=1, le=5)
    effort: ImprovementEffort
    risks: list[ShortText] = Field(max_length=6)
    required_evidence: list[ShortText] = Field(max_length=8)
    validation_step: ShortText


class ImprovementPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: ShortText
    weaknesses: list[WeaknessAnalysis] = Field(min_length=1, max_length=8)
    proposals: list[ImprovementProposal] = Field(min_length=1, max_length=6)
    recommended_strategy: ShortText
    builder_instructions: list[ShortText] = Field(min_length=1, max_length=10)
    research_questions: list[ShortText] = Field(max_length=10)
    next_steps: list[ShortText] = Field(min_length=1, max_length=10)
    stop_conditions: list[ShortText] = Field(max_length=8)


class ImprovementPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    round_id: UUID | None
    idea_version_id: UUID
    score_id: UUID
    decision_id: UUID
    agent_run_id: UUID
    version: int = Field(ge=1)
    source_score: int = Field(ge=0, le=100)
    source_confidence: float = Field(ge=0, le=1)
    plan: ImprovementPlanOutput
    created_at: datetime
