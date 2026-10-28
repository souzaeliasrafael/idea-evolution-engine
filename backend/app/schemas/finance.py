from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import AgentType, BillingCostSource, BillingSyncStatus, ProjectStatus


Money = Annotated[Decimal, Field(max_digits=18, decimal_places=6)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]


class FinanceSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=30, ge=1, le=365)


class ManualCostCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    provider: Annotated[str, Field(min_length=1, max_length=100)]
    period_start: datetime
    period_end: datetime
    amount: NonNegativeMoney
    currency: Annotated[str, Field(pattern=r"^USD$")] = "USD"
    model: Annotated[str, Field(max_length=200)] | None = None
    line_item: Annotated[str, Field(max_length=300)] | None = None
    note: Annotated[str, Field(max_length=2000)] | None = None

    @model_validator(mode="after")
    def require_bounded_period(self) -> "ManualCostCreate":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class ProviderCostEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    provider: str
    source: BillingCostSource
    period_start: datetime
    period_end: datetime
    amount: NonNegativeMoney
    currency: str
    model: str | None
    line_item: str | None
    external_project_id: str | None
    external_api_key_id: str | None
    quantity: Decimal | None
    quantity_unit: str | None
    details: dict[str, object]
    created_at: datetime
    updated_at: datetime


class BillingSyncRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    provider: str
    status: BillingSyncStatus
    period_start: datetime
    period_end: datetime
    entries_seen: int = Field(ge=0)
    entries_written: int = Field(ge=0)
    error: str | None
    started_at: datetime
    completed_at: datetime


class FinanceSummaryRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated_cost: NonNegativeMoney
    reconciled_cost: NonNegativeMoney
    variance: Money
    all_time_estimated_cost: NonNegativeMoney
    configured_budget: NonNegativeMoney
    total_runs: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    web_search_calls: int = Field(ge=0)
    tool_cost: NonNegativeMoney
    projects_at_or_over_budget: int = Field(ge=0)
    unpriced_runs: int = Field(ge=0)
    unsupported_currency_entries: int = Field(ge=0)


class ProviderFinanceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    estimated_cost: NonNegativeMoney
    reconciled_cost: NonNegativeMoney
    variance: Money
    runs: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    web_search_calls: int = Field(ge=0)
    tool_cost: NonNegativeMoney
    models: list[str]
    connector_configured: bool
    last_synced_at: datetime | None


class ModelFinanceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    runs: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    web_search_calls: int = Field(ge=0)
    tool_cost: NonNegativeMoney
    estimated_cost: NonNegativeMoney
    reconciled_cost: NonNegativeMoney | None


class AgentFinanceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentType
    runs: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    web_search_calls: int = Field(ge=0)
    tool_cost: NonNegativeMoney
    estimated_cost: NonNegativeMoney


class ProjectFinanceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    name: str
    status: ProjectStatus
    runs: int = Field(ge=0)
    period_estimated_cost: NonNegativeMoney
    all_time_estimated_cost: NonNegativeMoney
    max_ai_budget: Decimal | None
    remaining_ai_budget: Decimal | None
    budget_exhausted: bool


class DailyFinanceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    estimated_cost: NonNegativeMoney
    reconciled_cost: NonNegativeMoney


class BillingConnectorRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    configured: bool
    supports_sync: bool
    last_sync_status: BillingSyncStatus | None
    last_synced_at: datetime | None
    guidance: str


class FinanceOverviewRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    period_start: datetime
    period_end: datetime
    currency: str = "USD"
    summary: FinanceSummaryRead
    by_provider: list[ProviderFinanceRead]
    by_model: list[ModelFinanceRead]
    by_agent: list[AgentFinanceRead]
    by_project: list[ProjectFinanceRead]
    daily: list[DailyFinanceRead]
    connectors: list[BillingConnectorRead]
    recent_cost_entries: list[ProviderCostEntryRead]
    recent_syncs: list[BillingSyncRead]
