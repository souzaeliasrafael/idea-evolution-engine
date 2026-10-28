from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CriticismSeverity
NonBlankText = Annotated[str, Field(min_length=1)]
BuilderShortText = Annotated[str, Field(min_length=1, max_length=600)]
BuilderLongText = Annotated[str, Field(min_length=1, max_length=2000)]
CriticShortText = Annotated[str, Field(min_length=1, max_length=300)]
CriticText = Annotated[str, Field(min_length=1, max_length=600)]


class BuilderConcept(BaseModel):
    """Bounded mutable fields; raw_idea is preserved exclusively by the server."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)]
    problem: BuilderLongText
    solution: BuilderLongText
    target_users: Annotated[list[BuilderShortText], Field(max_length=8)]
    value_proposition: BuilderLongText
    possible_use_cases: Annotated[list[BuilderShortText], Field(max_length=8)]
    business_models: Annotated[list[BuilderShortText], Field(max_length=8)]
    technical_assumptions: Annotated[list[BuilderShortText], Field(max_length=8)]
    business_assumptions: Annotated[list[BuilderShortText], Field(max_length=8)]
    unknowns: Annotated[list[BuilderShortText], Field(max_length=8)]
    risks: Annotated[list[BuilderShortText], Field(max_length=8)]
    initial_mvp: BuilderLongText


class BuilderOutput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    improvements: Annotated[list[BuilderShortText], Field(max_length=6)]
    problems_solved: Annotated[list[BuilderShortText], Field(max_length=6)]
    unresolved_problems: Annotated[list[BuilderShortText], Field(max_length=6)]
    new_hypotheses: Annotated[list[BuilderShortText], Field(max_length=6)]
    proposed_changes: Annotated[list[BuilderShortText], Field(max_length=6)]
    new_concept: BuilderConcept


class CriticismOutput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)]
    severity: CriticismSeverity
    claim: CriticText
    reason: CriticText
    affected_hypotheses: Annotated[
        list[CriticShortText], Field(max_length=5)
    ]
    evidence_needed: CriticText
    condition_that_refutes_criticism: CriticText


class CriticOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criticisms: Annotated[list[CriticismOutput], Field(min_length=1, max_length=5)]


class CriticismRead(CriticismOutput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    idea_version_id: UUID
    agent_run_id: UUID
    created_at: datetime
