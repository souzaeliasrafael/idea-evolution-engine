import pytest
from httpx import AsyncClient

from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


async def test_voice_message_runs_full_cycle_and_persists_judge_reply(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects",
        json={"name": "Voice project", "raw_idea": "Validate ideas by voice"},
    )
    project_id = created.json()["id"]
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(
        f"/projects/{project_id}/judge-chat",
        json={
            "message": "Considere pequenas empresas e me diga o principal risco.",
            "input_mode": "VOICE",
        },
    )
    history = await client.get(f"/projects/{project_id}/judge-chat")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["input_mode"] == "VOICE"
    assert body["decision"] == "RESEARCH"
    assert body["score"] == 60
    assert body["confidence"] == 0.2
    assert "ciclo completo" in body["judge_response"]
    assert "score é 60 de 100" in body["judge_response"]
    assert body["decision_id"] is not None
    assert history.status_code == 200
    assert history.json() == [body]
    assert "pequenas empresas" in rounds.json()[0]["human_context"]
    assert [call.role for call in provider.calls] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
        "CRITIC",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
        "IMPROVER",
    ]


async def test_judge_chat_validates_message_and_unknown_project(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects", json={"name": "Chat validation", "raw_idea": "An idea"}
    )
    project_id = created.json()["id"]

    empty = await client.post(
        f"/projects/{project_id}/judge-chat",
        json={"message": "   ", "input_mode": "TEXT"},
    )
    unknown = await client.get(
        "/projects/00000000-0000-0000-0000-000000000000/judge-chat"
    )

    assert empty.status_code == 422
    assert unknown.status_code == 404


async def test_blocked_message_does_not_pollute_conversation_or_next_context(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects",
        json={
            "name": "No chat budget",
            "raw_idea": "An idea",
            "max_ai_budget": "0",
        },
    )
    project_id = created.json()["id"]

    blocked = await client.post(
        f"/projects/{project_id}/judge-chat",
        json={"message": "This must not be queued", "input_mode": "TEXT"},
    )
    history = await client.get(f"/projects/{project_id}/judge-chat")
    project = await client.get(f"/projects/{project_id}")

    assert blocked.status_code == 409
    assert history.json() == []
    assert project.json()["next_round_context"] is None
