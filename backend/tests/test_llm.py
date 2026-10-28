import json

import pytest

from app.agents.structurer import IdeaStructurer
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.prompts import PromptNotFoundError, load_prompt
from app.llm.providers.mock import MockLLMProvider


pytestmark = pytest.mark.anyio


async def test_provider_contract_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


async def test_mock_provider_returns_configured_response_and_records_call() -> None:
    provider = MockLLMProvider([json.dumps({"result": "ok"})])
    request = LLMRequest(role="STRUCTURER", prompt="A versioned prompt", input_data={})

    response = await provider.generate(request)

    assert json.loads(response.content) == {"result": "ok"}
    assert response.model == "mock-llm-v1"
    assert response.estimated_cost == 0
    assert provider.calls == [request]


async def test_mock_provider_can_simulate_provider_error() -> None:
    provider = MockLLMProvider([RuntimeError("provider unavailable")])
    request = LLMRequest(role="STRUCTURER", prompt="A versioned prompt", input_data={})

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await provider.generate(request)


async def test_versioned_prompt_is_loaded_from_file() -> None:
    prompt = load_prompt("structurer", "v1")

    assert "Preserve `raw_idea` exactly" in prompt
    assert "valid JSON only" in prompt


async def test_missing_or_unsafe_prompt_is_rejected() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("structurer", "v999")
    with pytest.raises(ValueError):
        load_prompt("../structurer", "v1")


async def test_typed_agent_retries_truncated_output_with_more_room_and_feedback() -> None:
    raw_idea = "A bounded retry"
    valid = {
        "title": "Retry",
        "raw_idea": raw_idea,
        "problem": "Responses may be truncated.",
        "solution": "Retry with a larger output allowance.",
        "target_users": ["Operators"],
        "value_proposition": "More reliable typed execution",
        "possible_use_cases": ["Large structured responses"],
        "business_models": ["Internal platform"],
        "technical_assumptions": ["The provider accepts a per-request limit"],
        "business_assumptions": ["Retries are budgeted"],
        "unknowns": ["Ideal output size"],
        "risks": ["A second response also exceeds the cap"],
        "initial_mvp": "Adaptive retry",
    }
    provider = MockLLMProvider(
        [
            LLMResponse(
                content='{"title":"partial"',
                model="mock-llm-v1",
                output_tokens=4096,
                finish_reason="max_output_tokens",
            ),
            json.dumps(valid),
        ]
    )
    agent = IdeaStructurer(provider, max_attempts=2, retry_max_output_tokens=16_384)

    result = await agent.run(project_name="Retry", raw_idea=raw_idea)

    assert result.output.title == "Retry"
    assert provider.calls[0].max_output_tokens is None
    assert provider.calls[1].max_output_tokens == 8192
    feedback = provider.calls[1].input_data["_retry_feedback"]
    assert "max_output_tokens" in feedback["previous_error"]
