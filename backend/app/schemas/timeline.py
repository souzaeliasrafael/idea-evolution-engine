from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AgentType


class TimelineItemRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    round_id: UUID | None
    round_number: int | None = Field(default=None, ge=1)
    agent: AgentType
    provider: str
    model: str
    prompt_version: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    web_search_calls: int = Field(ge=0)
    tool_cost: Decimal = Field(ge=0)
    web_sources: list[dict[str, str]]
    estimated_cost: Decimal = Field(ge=0)
    succeeded: bool
    error: str | None
    created_at: datetime
