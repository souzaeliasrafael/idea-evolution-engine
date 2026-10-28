from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebSearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_calls: int = Field(default=2, ge=1, le=10)
    context_size: str = Field(default="low", pattern=r"^(low|medium|high)$")


class WebSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    title: str = ""


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    input_data: dict[str, Any]
    output_schema_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    output_schema: dict[str, Any] | None = None
    web_search: WebSearchConfig | None = None
    max_output_tokens: int | None = Field(default=None, ge=256, le=131_072)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    model: str = Field(min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    web_search_calls: int = Field(default=0, ge=0)
    tool_cost: Decimal = Field(default=Decimal("0"), ge=0)
    web_sources: tuple[WebSource, ...] = ()
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)
    finish_reason: str | None = None


class LLMProvider(ABC):
    _bound_provider_name: str | None = None

    @property
    def provider_name(self) -> str:
        if self._bound_provider_name:
            return self._bound_provider_name
        return type(self).__name__.removesuffix("Provider").lower()

    def bind_provider_name(self, name: str) -> None:
        self._bound_provider_name = name.strip().lower()

    @property
    def supports_web_search(self) -> bool:
        return False

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier used for observability."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one response without exposing a vendor SDK to agents."""
