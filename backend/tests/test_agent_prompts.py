import pytest
from httpx import AsyncClient

from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


async def test_prompts_can_be_versioned_used_and_reset_from_api(
    client: AsyncClient,
) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    defaults = await client.get("/agent-prompts")
    assert defaults.status_code == 200
    assert len(defaults.json()) == 10
    default_critic = next(
        item for item in defaults.json() if item["agent"] == "CRITIC"
    )
    assert default_critic["version"] == "v1"
    assert default_critic["customized"] is False

    custom_content = (
        "Prioritize the three most consequential and falsifiable risks. "
        "Keep every criticism concise and actionable."
    )
    updated = await client.put(
        "/agent-prompts/CRITIC", json={"content": custom_content}
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == "custom-v1"
    assert updated.json()["customized"] is True

    project = await client.post(
        "/projects", json={"name": "Prompt control", "raw_idea": "Test prompts"}
    )
    project_id = project.json()["id"]
    assert (await client.post(f"/projects/{project_id}/structure")).status_code == 201
    assert (await client.post(f"/projects/{project_id}/critic")).status_code == 200

    critic_call = next(call for call in provider.calls if call.role == "CRITIC")
    assert critic_call.prompt == custom_content
    assert critic_call.output_schema_name == "critic_output"
    assert critic_call.output_schema is not None
    assert critic_call.output_schema["additionalProperties"] is False

    timeline = await client.get(f"/projects/{project_id}/timeline")
    critic_run = next(
        item for item in timeline.json() if item["agent"] == "CRITIC"
    )
    assert critic_run["prompt_version"] == "custom-v1"

    second = await client.put(
        "/agent-prompts/CRITIC",
        json={"content": custom_content + " Focus on willingness to pay."},
    )
    history = await client.get("/agent-prompts/CRITIC/versions")
    assert second.json()["version"] == "custom-v2"
    assert [item["version"] for item in history.json()] == [2, 1]
    assert [item["is_active"] for item in history.json()] == [True, False]

    reset = await client.delete("/agent-prompts/CRITIC")
    assert reset.status_code == 200
    assert reset.json()["customized"] is False
    assert reset.json()["version"] == "v1"


async def test_prompt_api_rejects_too_short_content(client: AsyncClient) -> None:
    response = await client.put(
        "/agent-prompts/BUILDER", json={"content": "too short"}
    )

    assert response.status_code == 422
