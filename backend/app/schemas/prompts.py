from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AgentType


class AgentPromptUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: Annotated[str, Field(min_length=20, max_length=20_000)]

    @field_validator("content")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Prompt cannot contain null bytes")
        return value


class AgentPromptRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentType
    content: str
    version: str
    customized: bool
    default_content: str
    default_version: str
    updated_at: datetime | None


class AgentPromptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent: AgentType
    version: int
    content: str
    is_active: bool
    created_at: datetime
