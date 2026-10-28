from functools import lru_cache
from decimal import Decimal

from app.core.config import get_settings
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.http import (
    ProviderConfigurationError,
    TokenPricing,
    require_api_key,
)
from app.llm.providers.mock import MockLLMProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.llm.router import (
    AgentModelConfig,
    LLMRouter,
    ProviderFactory,
    ProviderRegistry,
    build_router,
)


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    settings = get_settings()
    registry = ProviderRegistry()
    registry.register(
        "mock", lambda config: MockLLMProvider(model_name=config.model)
    )
    registry.register(
        "openai",
        lambda config: OpenAIProvider(
            model_name=config.model,
            api_key=require_api_key(
                _secret_value(settings.openai_api_key), "OPENAI_API_KEY"
            ),
            base_url=settings.openai_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_request_timeout_seconds,
            pricing=_cloud_pricing(config, settings.allow_unpriced_cloud_models),
            web_search_cost_per_call=settings.openai_web_search_cost_per_call,
        ),
    )
    registry.register(
        "anthropic",
        lambda config: AnthropicProvider(
            model_name=config.model,
            api_key=require_api_key(
                _secret_value(settings.anthropic_api_key), "ANTHROPIC_API_KEY"
            ),
            base_url=settings.anthropic_base_url,
            api_version=settings.anthropic_version,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_request_timeout_seconds,
            pricing=_cloud_pricing(config, settings.allow_unpriced_cloud_models),
        ),
    )
    registry.register(
        "gemini",
        lambda config: GeminiProvider(
            model_name=config.model,
            api_key=require_api_key(
                _secret_value(settings.gemini_api_key), "GEMINI_API_KEY"
            ),
            base_url=settings.gemini_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_request_timeout_seconds,
            pricing=_cloud_pricing(config, settings.allow_unpriced_cloud_models),
        ),
    )

    def compatible_factory(config: AgentModelConfig) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            model_name=config.model,
            api_key=_secret_value(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_request_timeout_seconds,
            pricing=_pricing(config),
        )

    for alias in ("openai-compatible", "openai_compatible", "compatible", "local"):
        registry.register(alias, compatible_factory)
    return registry


@lru_cache
def get_llm_router() -> LLMRouter:
    return build_router(get_settings(), get_provider_registry())


def register_provider_adapter(name: str, factory: ProviderFactory) -> None:
    """Register an adapter factory during application startup, then rebuild routing."""

    get_provider_registry().register(name, factory)
    get_llm_router.cache_clear()


def _secret_value(secret: object) -> str | None:
    get_secret_value = getattr(secret, "get_secret_value", None)
    return get_secret_value() if callable(get_secret_value) else None


def _pricing(config: AgentModelConfig) -> TokenPricing:
    known_cached_rates = {
        ("openai", "gpt-5-mini"): Decimal("0.025"),
        ("openai", "gpt-5.6-luna"): Decimal("0.02"),
    }
    cached_rate = config.cached_input_cost_per_million
    if cached_rate is None:
        cached_rate = known_cached_rates.get(
            (config.provider.strip().lower(), config.model.strip().lower())
        )
    return TokenPricing(
        input_per_million=config.input_cost_per_million,
        cached_input_per_million=cached_rate,
        output_per_million=config.output_cost_per_million,
    )


def _cloud_pricing(
    config: AgentModelConfig, allow_unpriced: bool
) -> TokenPricing:
    pricing = _pricing(config)
    if (
        pricing.input_per_million == 0
        and pricing.output_per_million == 0
        and not allow_unpriced
    ):
        raise ProviderConfigurationError(
            f"Pricing is required for cloud model {config.model!r}; configure the "
            "agent input/output cost per million tokens or set "
            "ALLOW_UNPRICED_CLOUD_MODELS=true explicitly"
        )
    return pricing
