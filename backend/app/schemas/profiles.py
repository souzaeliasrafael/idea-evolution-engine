from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import AgentType


Price = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6)]


class AgentProfileModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    provider: Annotated[str, Field(min_length=1, max_length=100)]
    model: Annotated[str, Field(min_length=1, max_length=200)]
    input_cost_per_million: Price = Decimal("0")
    cached_input_cost_per_million: Price | None = None
    output_cost_per_million: Price = Decimal("0")


class AgentProfileCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=2000)] = ""
    agents: dict[AgentType, AgentProfileModel]

    @model_validator(mode="after")
    def require_every_agent(self) -> "AgentProfileCreate":
        required = {
            AgentType.STRUCTURER,
            AgentType.BUILDER,
            AgentType.RESEARCHER,
            AgentType.CRITIC,
            AgentType.JUDGE,
        }
        missing = required - set(self.agents)
        if missing:
            names = ", ".join(sorted(agent.value for agent in missing))
            raise ValueError(f"Profile is missing agent configurations: {names}")
        return self


class AgentProfileUpdate(AgentProfileCreate):
    pass


class AgentProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    agents: dict[AgentType, AgentProfileModel]
    created_at: datetime
    updated_at: datetime


class ProjectProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_profile_id: UUID | None
