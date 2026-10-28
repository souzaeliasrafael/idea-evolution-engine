from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


class BillingConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class BillingCostItem:
    period_start: datetime
    period_end: datetime
    amount: Decimal
    currency: str = "USD"
    model: str | None = None
    line_item: str | None = None
    external_project_id: str | None = None
    external_api_key_id: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class BillingProviderAdapter(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider key used by profiles and financial reports."""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether the provider has the administrative billing credential."""

    @abstractmethod
    async def fetch_costs(
        self, *, start: datetime, end: datetime
    ) -> list[BillingCostItem]:
        """Fetch authoritative provider costs for a bounded period."""
