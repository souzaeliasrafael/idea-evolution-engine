from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AgentRun
from app.domain.enums import AgentType
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


async def test_blueprint_uses_research_context_and_persists_every_stage(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    project = await client.post(
        "/projects",
        json={"name": "Blueprint", "raw_idea": "A traceable product idea"},
    )
    project_id = project.json()["id"]
    structured = await client.post(f"/projects/{project_id}/structure")

    generated = await client.post(
        f"/projects/{project_id}/development-blueprints",
        json={
            "architecture_alternatives": 2,
            "user_context": "Prefer a small, reversible first release.",
            "max_ai_budget": "1.00",
        },
    )
    listed = await client.get(f"/projects/{project_id}/development-blueprints")

    assert structured.status_code == 201
    assert generated.status_code == 201
    body = generated.json()
    assert body["status"] == "COMPLETED"
    assert body["product_definition"]["functional_requirements"][0]["id"] == "FR-001"
    assert len(body["architecture_options"]) == 2
    assert body["technical_review"]["recommended_option"] == "Modular baseline 1"
    assert body["final_blueprint"]["phases"][0]["number"] == 1
    assert body["estimated_cost"] == "0.000000"
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]

    async with session_maker() as session:
        blueprint_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(
                        AgentRun.agent.in_(
                            {
                                AgentType.PRODUCT_ARCHITECT,
                                AgentType.SOLUTION_ARCHITECT,
                                AgentType.TECHNICAL_CRITIC,
                                AgentType.ROADMAP_PLANNER,
                            }
                        )
                    )
                )
            ).all()
        )
    assert len(blueprint_runs) == 5
    assert len(body["agent_run_ids"]) == 5
    assert sum((item.estimated_cost for item in blueprint_runs), Decimal("0")) == 0

