from decimal import Decimal
import json

import httpx
import pytest

from app.core.config import get_settings
from app.domain.enums import AgentType
from app.llm.base import LLMRequest, WebSearchConfig
from app.llm.dependencies import (
    get_llm_router,
    get_provider_registry,
)
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.http import (
    ProviderConfigurationError,
    ProviderRequestError,
    TokenPricing,
    require_api_key,
)
from app.llm.providers.mock import MockLLMProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider


pytestmark = pytest.mark.anyio


REQUEST = LLMRequest(
    role="CRITIC",
    prompt="Return valid JSON only.",
    input_data={"idea": "A traceable evaluation engine"},
    output_schema_name="critic_output",
    output_schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
)
PRICING = TokenPricing(
    input_per_million=Decimal("2"), output_per_million=Decimal("10")
)


def test_token_pricing_applies_the_cached_input_rate_only_to_cached_tokens() -> None:
    pricing = TokenPricing(
        input_per_million=Decimal("0.25"),
        cached_input_per_million=Decimal("0.025"),
        output_per_million=Decimal("2"),
    )

    assert pricing.estimate(1_000_000, 100_000, 400_000) == Decimal("0.360000")


def client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_openai_responses_adapter_maps_request_usage_and_cost() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://api.openai.test/v1/responses"
        assert request.headers["authorization"] == "Bearer openai-secret"
        assert payload["instructions"] == REQUEST.prompt
        assert json.loads(payload["input"]) == REQUEST.input_data
        assert payload["max_output_tokens"] == 4096
        assert payload["store"] is False
        assert payload["text"] == {
            "format": {
                "type": "json_schema",
                "name": "critic_output",
                "strict": True,
                "schema": REQUEST.output_schema,
            }
        }
        return httpx.Response(
            200,
            json={
                "model": "gpt-test-resolved",
                "output_text": '{"ok":true}',
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "input_tokens_details": {"cached_tokens": 40},
                    "output_tokens_details": {"reasoning_tokens": 15},
                },
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = OpenAIProvider(
            model_name="gpt-test",
            api_key="openai-secret",
            base_url="https://api.openai.test/v1",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        result = await provider.generate(REQUEST)

    assert result.content == '{"ok":true}'
    assert result.model == "gpt-test-resolved"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cached_input_tokens == 40
    assert result.reasoning_tokens == 15
    assert result.estimated_cost == Decimal("0.000700")


async def test_openai_adapter_preserves_incomplete_usage_for_auditing() -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "model": "gpt-test-resolved",
                "output_text": '{"ok":',
                "usage": {"input_tokens": 100, "output_tokens": 4096},
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = OpenAIProvider(
            model_name="gpt-test",
            api_key="openai-secret",
            base_url="https://api.openai.test/v1",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        result = await provider.generate(REQUEST)

    assert result.content == '{"ok":'
    assert result.finish_reason == "max_output_tokens"
    assert result.output_tokens == 4096
    assert result.estimated_cost > 0


async def test_openai_web_search_maps_tools_sources_and_tool_cost() -> None:
    web_request = REQUEST.model_copy(
        update={"web_search": WebSearchConfig(max_calls=2, context_size="low")}
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"] == [
            {"type": "web_search", "search_context_size": "low"}
        ]
        assert payload["tool_choice"] == "required"
        assert payload["max_tool_calls"] == 2
        assert payload["include"] == ["web_search_call.action.sources"]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-test-resolved",
                "output_text": '{"ok":true}',
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "type": "search",
                            "sources": [{"url": "https://example.com/report"}],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"ok":true}',
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.com/report",
                                        "title": "Primary report",
                                    }
                                ],
                            }
                        ],
                    },
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = OpenAIProvider(
            model_name="gpt-test",
            api_key="openai-secret",
            base_url="https://api.openai.test/v1",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            web_search_cost_per_call=Decimal("0.01"),
            client=client,
        )
        result = await provider.generate(web_request)

    assert result.web_search_calls == 1
    assert result.tool_cost == Decimal("0.010000")
    assert result.estimated_cost == Decimal("0.010700")
    assert [source.model_dump() for source in result.web_sources] == [
        {"url": "https://example.com/report", "title": "Primary report"}
    ]


async def test_anthropic_messages_adapter_maps_request_and_response() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://api.anthropic.test/v1/messages"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert payload["system"] == REQUEST.prompt
        assert json.loads(payload["messages"][0]["content"]) == REQUEST.input_data
        return httpx.Response(
            200,
            json={
                "model": "claude-test-resolved",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 10,
                },
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = AnthropicProvider(
            model_name="claude-test",
            api_key="anthropic-secret",
            base_url="https://api.anthropic.test",
            api_version="2023-06-01",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        result = await provider.generate(REQUEST)

    assert result.content == '{"ok":true}'
    assert result.input_tokens == 95
    assert result.output_tokens == 20
    assert result.cached_input_tokens == 10
    assert result.estimated_cost == Decimal("0.000390")


async def test_gemini_generate_content_adapter_requests_json_output() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == (
            "https://gemini.test/v1beta/models/gemini-test:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert payload["systemInstruction"]["parts"][0]["text"] == REQUEST.prompt
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["maxOutputTokens"] == 4096
        return httpx.Response(
            200,
            json={
                "modelVersion": "gemini-test-resolved",
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok":true}'}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 75,
                    "candidatesTokenCount": 25,
                    "thoughtsTokenCount": 10,
                    "cachedContentTokenCount": 12,
                },
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = GeminiProvider(
            model_name="models/gemini-test",
            api_key="gemini-secret",
            base_url="https://gemini.test/v1beta",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        result = await provider.generate(REQUEST)

    assert result.content == '{"ok":true}'
    assert result.model == "gemini-test-resolved"
    assert result.output_tokens == 35
    assert result.cached_input_tokens == 12
    assert result.reasoning_tokens == 10
    assert result.estimated_cost == Decimal("0.000500")


async def test_openai_compatible_adapter_supports_local_server_without_key() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "http://local.test/v1/chat/completions"
        assert "authorization" not in request.headers
        assert payload["messages"][0] == {
            "role": "system",
            "content": REQUEST.prompt,
        }
        return httpx.Response(
            200,
            json={
                "model": "local-model",
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = OpenAICompatibleProvider(
            model_name="local-model",
            api_key=None,
            base_url="http://local.test/v1",
            max_output_tokens=2048,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        result = await provider.generate(REQUEST)

    assert result.content == '{"ok":true}'
    assert result.input_tokens == 10
    assert result.output_tokens == 5


async def test_provider_http_errors_are_bounded_and_do_not_expose_api_key() -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid credential"})

    async with client_for(httpx.MockTransport(respond)) as client:
        provider = OpenAIProvider(
            model_name="gpt-test",
            api_key="never-log-this-secret",
            base_url="https://api.openai.test/v1",
            max_output_tokens=4096,
            timeout_seconds=10,
            pricing=PRICING,
            client=client,
        )
        with pytest.raises(ProviderRequestError) as caught:
            await provider.generate(REQUEST)

    assert "HTTP 401" in str(caught.value)
    assert "never-log-this-secret" not in str(caught.value)


def test_selected_cloud_provider_requires_its_credential() -> None:
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        require_api_key(None, "OPENAI_API_KEY")


def test_cloud_provider_rejects_unknown_zero_pricing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUILDER_PROVIDER", "openai")
    monkeypatch.setenv("BUILDER_MODEL", "gpt-priced")
    monkeypatch.setenv("BUILDER_INPUT_COST_PER_MILLION", "0")
    monkeypatch.setenv("BUILDER_OUTPUT_COST_PER_MILLION", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("ALLOW_UNPRICED_CLOUD_MODELS", "false")
    get_settings.cache_clear()
    get_provider_registry.cache_clear()
    get_llm_router.cache_clear()
    try:
        with pytest.raises(ProviderConfigurationError, match="Pricing is required"):
            get_llm_router()
    finally:
        get_llm_router.cache_clear()
        get_provider_registry.cache_clear()
        get_settings.cache_clear()


def test_builtin_registry_routes_every_agent_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "STRUCTURER_PROVIDER": "mock",
        "STRUCTURER_MODEL": "mock-structure",
        "BUILDER_PROVIDER": "openai",
        "BUILDER_MODEL": "gpt-builder",
        "BUILDER_INPUT_COST_PER_MILLION": "1.25",
        "BUILDER_OUTPUT_COST_PER_MILLION": "5",
        "CRITIC_PROVIDER": "anthropic",
        "CRITIC_MODEL": "claude-critic",
        "CRITIC_INPUT_COST_PER_MILLION": "2",
        "CRITIC_OUTPUT_COST_PER_MILLION": "8",
        "RESEARCHER_PROVIDER": "gemini",
        "RESEARCHER_MODEL": "gemini-research",
        "RESEARCHER_INPUT_COST_PER_MILLION": "0.5",
        "RESEARCHER_OUTPUT_COST_PER_MILLION": "2",
        "JUDGE_PROVIDER": "local",
        "JUDGE_MODEL": "qwen-judge",
        "OPENAI_API_KEY": "test-openai",
        "ANTHROPIC_API_KEY": "test-anthropic",
        "GEMINI_API_KEY": "test-gemini",
        "OPENAI_COMPATIBLE_BASE_URL": "http://localhost:11434/v1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    get_provider_registry.cache_clear()
    get_llm_router.cache_clear()
    try:
        router = get_llm_router()
        assert isinstance(router.provider_for(AgentType.STRUCTURER), MockLLMProvider)
        assert isinstance(router.provider_for(AgentType.BUILDER), OpenAIProvider)
        assert isinstance(router.provider_for(AgentType.CRITIC), AnthropicProvider)
        assert isinstance(router.provider_for(AgentType.RESEARCHER), GeminiProvider)
        assert isinstance(
            router.provider_for(AgentType.JUDGE), OpenAICompatibleProvider
        )
        builder = router.provider_for(AgentType.BUILDER)
        assert builder.model_name == "gpt-builder"
        assert builder.pricing.input_per_million == Decimal("1.25")
    finally:
        get_llm_router.cache_clear()
        get_provider_registry.cache_clear()
        get_settings.cache_clear()
