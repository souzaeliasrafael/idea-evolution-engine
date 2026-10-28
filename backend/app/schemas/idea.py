from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AgentType


NonBlankText = Annotated[str, Field(min_length=1)]


class IdeaConcept(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: NonBlankText
    raw_idea: NonBlankText
    problem: NonBlankText
    solution: NonBlankText
    target_users: list[NonBlankText]
    value_proposition: NonBlankText
    possible_use_cases: list[NonBlankText]
    business_models: list[NonBlankText]
    technical_assumptions: list[NonBlankText]
    business_assumptions: list[NonBlankText]
    unknowns: list[NonBlankText]
    risks: list[NonBlankText]
    initial_mvp: NonBlankText


class IdeaVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version: int = Field(ge=0)
    parent_version_id: UUID | None
    reason_for_change: str
    created_by: AgentType
    changes: list[str]
    concept: IdeaConcept
    created_at: datetime

