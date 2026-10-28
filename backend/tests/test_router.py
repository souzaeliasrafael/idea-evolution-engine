import pytest

from app.core.config import Settings
from app.domain.enums import AgentType
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import (
    AgentModelConfig,
    ProviderRegistry,
    UnknownProviderError,
    build_router,
    config_for_agent,
)


def test_router_resolves_independent_model_for_every_agent() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        llm_model="fallback-model",
        structurer_model="structure-model",
        builder_model="builder-model",
        critic_model="critic-model",
        researcher_model="research-model",
        judge_model="judge-model",
    )
    registry = ProviderRegistry()
    registry.register(
        "mock", lambda config: MockLLMProvider(model_name=config.model)
    )

    router = build_router(settings, registry)

    assert router.provider_for(AgentType.STRUCTURER).model_name == "structure-model"
    assert router.provider_for(AgentType.BUILDER).model_name == "builder-model"
    assert router.provider_for(AgentType.CRITIC).model_name == "critic-model"
    assert router.provider_for(AgentType.RESEARCHER).model_name == "research-model"
    assert router.provider_for(AgentType.JUDGE).model_name == "judge-model"
    assert router.provider_for(AgentType.BUILDER) is not router.provider_for(
        AgentType.CRITIC
    )


def test_agent_configuration_falls_back_to_safe_backend_defaults() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        llm_model="fallback-model",
        builder_provider=None,
        builder_model=None,
    )

    config = config_for_agent(settings, AgentType.BUILDER)

    assert config == AgentModelConfig(
        provider="mock",
        model="fallback-model",
        input_cost_per_million=0,
        output_cost_per_million=0,
    )


def test_registry_rejects_unknown_or_duplicate_adapters() -> None:
    registry = ProviderRegistry()
    registry.register(
        "mock", lambda config: MockLLMProvider(model_name=config.model)
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            "MOCK", lambda config: MockLLMProvider(model_name=config.model)
        )
    with pytest.raises(UnknownProviderError, match="No adapter is registered"):
        registry.create(AgentModelConfig(provider="unknown", model="some-model"))
