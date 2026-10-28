import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Round, WorkflowExecution
from app.domain.enums import RoundStatus, WorkflowExecutionStatus
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.base import LLMRequest, LLMResponse
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


class PausingCriticProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.critic_started = asyncio.Event()
        self.release_critic = asyncio.Event()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if request.role == "CRITIC" and not self.release_critic.is_set():
            self.critic_started.set()
            await self.release_critic.wait()
        return await super().generate(request)


async def test_timeline_and_criticism_feeds_support_project_screen(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects", json={"name": "Visible workflow", "raw_idea": "A raw idea"}
    )
    project_id = created.json()["id"]
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    run = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    timeline = await client.get(f"/projects/{project_id}/timeline")
    criticisms = await client.get(f"/projects/{project_id}/criticisms")

    assert run.status_code == 200
    assert timeline.status_code == 200
    assert [item["agent"] for item in timeline.json()] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
        "CRITIC",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
        "IMPROVER",
    ]
    assert timeline.json()[0]["round_number"] is None
    assert {item["round_number"] for item in timeline.json()[1:]} == {1}
    assert all(item["succeeded"] for item in timeline.json())
    assert criticisms.status_code == 200
    assert criticisms.json()[0]["severity"] == "MEDIUM"


async def test_timeline_and_criticisms_return_404_for_unknown_project(
    client: AsyncClient,
) -> None:
    project_id = uuid4()

    timeline = await client.get(f"/projects/{project_id}/timeline")
    criticisms = await client.get(f"/projects/{project_id}/criticisms")

    assert timeline.status_code == criticisms.status_code == 404


async def test_workflow_status_exposes_agent_and_supports_safe_cancellation(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects",
        json={
            "name": "Live status",
            "raw_idea": "Show progress",
            "agent_plan": {"builder": 1, "researcher": 1, "critic": 3},
        },
    )
    project_id = created.json()["id"]
    provider = PausingCriticProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    before = await client.get(f"/projects/{project_id}/run-status")
    run_task = asyncio.create_task(
        client.post(f"/projects/{project_id}/run", json={"max_rounds": 1})
    )
    try:
        await asyncio.wait_for(provider.critic_started.wait(), timeout=2)
        during = await client.get(f"/projects/{project_id}/run-status")
        cancellation = await client.post(f"/projects/{project_id}/run-cancel")
    finally:
        provider.release_critic.set()
    run = await run_task
    after = await client.get(f"/projects/{project_id}/run-status")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert before.status_code == during.status_code == after.status_code == 200
    assert before.json()["status"] == "IDLE"
    assert during.json()["status"] == "RUNNING"
    assert during.json()["current_agent"] == "CRITIC"
    assert during.json()["workflow_stage"] == "Crítica do conteúdo acumulado"
    assert during.json()["current_round"] == 1
    assert during.json()["round_position"] == 1
    assert during.json()["requested_rounds"] == 1
    assert during.json()["agent_iteration"] == 1
    # A profile depth is now a ceiling; a first pass starts with one call.
    assert during.json()["agent_iterations"] == 1
    assert cancellation.status_code == 200
    assert cancellation.json()["status"] == "CANCELLING"
    assert run.status_code == 200
    assert run.json()["stop_reason"] == "USER_CANCELLED"
    assert [call.role for call in provider.calls] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
    ]
    assert rounds.json()[0]["status"] == "CANCELLED"
    assert after.json()["status"] == "IDLE"

    no_active_run = await client.post(f"/projects/{project_id}/run-cancel")
    assert no_active_run.status_code == 409

    unknown = await client.get(f"/projects/{uuid4()}/run-status")
    assert unknown.status_code == 404


async def test_stale_workflow_releases_its_orphaned_running_round(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    created = await client.post(
        "/projects",
        json={"name": "Restart recovery", "raw_idea": "Recover safely"},
    )
    project_id = created.json()["id"]
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        MockLLMProvider()
    )
    structured = await client.post(f"/projects/{project_id}/structure")
    assert structured.status_code == 201
    stale_at = datetime.now(UTC) - timedelta(minutes=2)
    async with session_maker() as session:
        workflow = await session.get(WorkflowExecution, project_id)
        assert workflow is not None
        workflow.status = WorkflowExecutionStatus.CANCELLING
        workflow.owner_id = "dead-worker"
        workflow.cancellation_requested = True
        workflow.updated_at = stale_at
        workflow.heartbeat_at = stale_at
        session.add(
            Round(
                project_id=project_id,
                round_number=1,
                status=RoundStatus.RUNNING,
                starting_version_id=structured.json()["id"],
            )
        )
        await session.commit()

    progress = await client.get(f"/projects/{project_id}/run-status")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert progress.status_code == 200
    assert progress.json()["status"] == "IDLE"
    assert rounds.status_code == 200
    assert rounds.json()[0]["status"] == "CANCELLED"
    assert "reinício do servidor" in rounds.json()[0]["error"]


async def test_frontend_origin_is_allowed_by_cors(client: AsyncClient) -> None:
    response = await client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
