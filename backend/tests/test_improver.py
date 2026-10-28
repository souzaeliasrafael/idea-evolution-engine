import pytest
from httpx import AsyncClient

from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


def use_provider(provider: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )


async def test_improver_requires_a_judgment_and_persists_a_typed_plan(
    client: AsyncClient,
) -> None:
    provider = MockLLMProvider()
    use_provider(provider)
    project = await client.post(
        "/projects", json={"name": "Improve me", "raw_idea": "A useful idea"}
    )
    project_id = project.json()["id"]
    assert (await client.post(f"/projects/{project_id}/structure")).status_code == 201

    before_judge = await client.post(f"/projects/{project_id}/improver")
    assert before_judge.status_code == 409

    assert (await client.post(f"/projects/{project_id}/judge")).status_code == 200
    generated = await client.post(f"/projects/{project_id}/improver")
    plans = await client.get(f"/projects/{project_id}/improvement-plans")
    timeline = await client.get(f"/projects/{project_id}/timeline")

    assert generated.status_code == 200
    assert generated.json()["version"] == 1
    assert generated.json()["source_score"] == 60
    assert generated.json()["plan"]["weaknesses"][0]["current_rating"] == 3
    assert generated.json()["plan"]["proposals"][0]["target_criteria"]
    assert plans.status_code == 200
    assert plans.json()[0]["id"] == generated.json()["id"]
    assert timeline.json()[-1]["agent"] == "IMPROVER"
    assert provider.calls[-1].role == "IMPROVER"
    assert provider.calls[-1].input_data["latest_score"]["score"] == 60


async def test_orchestrator_runs_improver_after_non_terminal_judge(
    client: AsyncClient,
) -> None:
    provider = MockLLMProvider()
    use_provider(provider)
    project = await client.post(
        "/projects", json={"name": "Automatic plan", "raw_idea": "A useful idea"}
    )
    project_id = project.json()["id"]

    run = await client.post(f"/projects/{project_id}/run", json={"max_rounds": 2})
    plans = await client.get(f"/projects/{project_id}/improvement-plans")
    second_round_research = [
        call
        for call in provider.calls
        if call.role == "RESEARCHER"
        and call.input_data.get("accumulated_context", {}).get("round_number") == 2
    ][0]

    assert run.status_code == 200
    assert [call.role for call in provider.calls].count("IMPROVER") == 2
    assert len(plans.json()) == 2
    assert second_round_research.input_data["accumulated_context"][
        "previous_improvement_plan"
    ]["recommended_strategy"]
