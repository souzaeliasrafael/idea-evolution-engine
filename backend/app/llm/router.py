from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings
from app.domain.enums import AgentType
from app.llm.base import LLMProvider


@dataclass(frozen=True)
class AgentModelConfig:
    provider: str
    model: str
    input_cost_per_million: Decimal = Decimal("0")
    cached_input_cost_per_million: Decimal | None = None
    output_cost_per_million: Decimal = Decimal("0")


ProviderFactory = Callable[[AgentModelConfig], LLMProvider]


class UnknownProviderError(LookupError):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("Provider name cannot be blank")
        if normalized_name in self._factories:
            raise ValueError(f"Provider adapter is already registered: {normalized_name}")
        self._factories[normalized_name] = factory

    def create(self, config: AgentModelConfig) -> LLMProvider:
        normalized_provider = config.provider.strip().lower()
        factory = self._factories.get(normalized_provider)
        if factory is None:
            raise UnknownProviderError(
                f"No adapter is registered for provider: {config.provider}"
            )
        provider = factory(config)
        provider.bind_provider_name(normalized_provider)
        return provider

    def supports(self, name: str) -> bool:
        return name.strip().lower() in self._factories


class LLMRouter:
    def __init__(self, providers: dict[AgentType, LLMProvider]) -> None:
        missing = set(AgentType) - set(providers)
        if missing:
            names = ", ".join(sorted(agent.value for agent in missing))
            raise ValueError(f"Missing provider configuration for: {names}")
        self._providers = dict(providers)

    def provider_for(self, agent: AgentType) -> LLMProvider:
        return self._providers[agent]

    @classmethod
    def from_single_provider(cls, provider: LLMProvider) -> "LLMRouter":
        return cls({agent: provider for agent in AgentType})


def config_for_agent(settings: Settings, agent: AgentType) -> AgentModelConfig:
    prefix = agent.value.lower()
    fallbacks = {
        AgentType.IMPROVER: AgentType.BUILDER,
        AgentType.PRODUCT_ARCHITECT: AgentType.BUILDER,
        AgentType.SOLUTION_ARCHITECT: AgentType.BUILDER,
        AgentType.TECHNICAL_CRITIC: AgentType.CRITIC,
        AgentType.ROADMAP_PLANNER: AgentType.JUDGE,
    }
    fallback = (
        config_for_agent(settings, fallbacks[agent])
        if agent in fallbacks
        else AgentModelConfig(
            provider=settings.llm_provider,
            model=settings.llm_model,
            input_cost_per_million=settings.llm_input_cost_per_million,
            cached_input_cost_per_million=settings.llm_cached_input_cost_per_million,
            output_cost_per_million=settings.llm_output_cost_per_million,
        )
    )
    provider = getattr(settings, f"{prefix}_provider") or fallback.provider
    model = getattr(settings, f"{prefix}_model") or fallback.model
    input_cost = (
        getattr(settings, f"{prefix}_input_cost_per_million")
        if getattr(settings, f"{prefix}_input_cost_per_million") is not None
        else fallback.input_cost_per_million
    )
    output_cost = (
        getattr(settings, f"{prefix}_output_cost_per_million")
        if getattr(settings, f"{prefix}_output_cost_per_million") is not None
        else fallback.output_cost_per_million
    )
    cached_input_cost = (
        getattr(settings, f"{prefix}_cached_input_cost_per_million")
        if getattr(settings, f"{prefix}_cached_input_cost_per_million") is not None
        else fallback.cached_input_cost_per_million
    )
    return AgentModelConfig(
        provider=provider,
        model=model,
        input_cost_per_million=input_cost,
        cached_input_cost_per_million=cached_input_cost,
        output_cost_per_million=output_cost,
    )


def build_router(settings: Settings, registry: ProviderRegistry) -> LLMRouter:
    return LLMRouter(
        {
            agent: registry.create(config_for_agent(settings, agent))
            for agent in AgentType
        }
    )
