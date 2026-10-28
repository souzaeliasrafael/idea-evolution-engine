from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ProjectStatus


NonBlankName = Annotated[str, Field(min_length=1, max_length=200)]
NonBlankIdea = Annotated[str, Field(min_length=1, max_length=50_000)]
NextRoundContext = Annotated[str, Field(min_length=1, max_length=20_000)]
BudgetAmount = Annotated[
    Decimal, Field(ge=0, max_digits=12, decimal_places=6)
]


class AgentExecutionPlan(BaseModel):
    """Number of calls made by each optional agent in every round."""

    model_config = ConfigDict(extra="forbid")

    builder: int = Field(default=1, ge=0, le=3)
    researcher: int = Field(default=1, ge=0, le=3)
    critic: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def require_at_least_one_agent(self) -> "AgentExecutionPlan":
        if self.builder + self.researcher + self.critic == 0:
            raise ValueError("at least one optional agent must be enabled")
        return self


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: NonBlankName
    raw_idea: NonBlankIdea
    max_ai_budget: BudgetAmount | None = None
    agent_profile_id: UUID | None = None
    agent_plan: AgentExecutionPlan = Field(default_factory=AgentExecutionPlan)


class ProjectBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_ai_budget: BudgetAmount | None


class ProjectAgentPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_plan: AgentExecutionPlan


class ProjectNextRoundContextUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    next_round_context: NextRoundContext | None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    raw_idea: str
    agent_profile_id: UUID | None
    agent_plan: AgentExecutionPlan
    status: ProjectStatus
    total_cost: Decimal
    max_ai_budget: Decimal | None
    next_round_context: str | None
    remaining_ai_budget: Decimal | None
    budget_exhausted: bool
    stagnation_detected: bool
    created_at: datetime
    updated_at: datetime
