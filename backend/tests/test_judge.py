import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AgentRun, DecisionRecord, ProjectScore
from app.domain.enums import AgentType, ScoreCriterion
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.schemas.judgment import JudgeAssessment


pytestmark = pytest.mark.anyio


def concept_payload() -> dict[str, object]:
    return {
        "title": "Structured idea",
        "raw_idea": "A raw idea",
        "problem": "Teams build before validating demand.",
        "solution": "A bounded evaluation workflow.",
        "target_users": ["Product teams"],
        "value_proposition": "Reduce waste before implementation.",
        "possible_use_cases": ["Product discovery"],
        "business_models": ["Subscription"],
        "technical_assumptions": ["LLMs can return typed JSON"],
        "business_assumptions": ["Teams will pay to reduce discovery risk"],
        "unknowns": ["Willingness to pay"],
        "risks": ["Low differentiation"],
        "initial_mvp": "Evaluate one idea with a bounded workflow.",
    }


def judge_payload(
    *,
    rating: int = 4,
    decision: str = "APPROVE",
    confidence: float = 0.8,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    return {
        "decision": decision,
        "criteria": [
            {
                "criterion": criterion.value,
                "rating": rating,
                "rationale": f"Assessment for {criterion.value}",
                "evidence_ids": [],
            }
            for criterion in ScoreCriterion
        ],
        "confidence": confidence,
        "reasoning_summary": "A typed judgment based on the available context.",
        "critical_blockers": blockers or [],
        "most_important_unknowns": ["Demand"],
        "next_actions": ["Proceed according to the decision"],
    }


def use_provider(provider: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )


async def create_structured_project(client: AsyncClient) -> tuple[str, dict[str, object]]:
    project = await client.post(
        "/projects", json={"name": "Judged project", "raw_idea": "A raw idea"}
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    use_provider(MockLLMProvider([json.dumps(concept_payload())]))
    version = await client.post(f"/projects/{project_id}/structure")
    assert version.status_code == 201
    return project_id, version.json()


async def test_judge_schema_rejects_invalid_decision() -> None:
    payload = judge_payload(decision="MAYBE")

    with pytest.raises(ValidationError):
        JudgeAssessment.model_validate(payload)


async def test_judge_computes_score_and_persists_decision(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, version = await create_structured_project(client)
    provider = MockLLMProvider(
        [json.dumps(judge_payload())], model_name="judge-model-only"
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/judge")
    scores = await client.get(f"/projects/{project_id}/scores")
    decisions = await client.get(f"/projects/{project_id}/decisions")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert response.status_code == 200
    assert response.json()["decision"] == "APPROVE"
    assert response.json()["score"] == 80
    assert response.json()["confidence"] == 0.8
    assert len(response.json()["score_breakdown"]) == 12
    assert scores.status_code == decisions.status_code == 200
    assert scores.json()[0]["total_score"] == 80
    assert scores.json()[0]["confidence"] == 0.8
    assert decisions.json()[0]["decision"] == "APPROVE"
    assert decisions.json()[0]["score"] == 80
    assert decisions.json()[0]["from_version_id"] == version["id"]
    assert len(versions.json()) == 1

    async with session_maker() as session:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.agent == AgentType.JUDGE)
        )
        score = await session.scalar(select(ProjectScore))
        decision = await session.scalar(select(DecisionRecord))
    assert run is not None and run.model == "judge-model-only"
    assert score is not None and decision is not None
    assert decision.agent_run_id == run.id
    assert decision.score_id == score.id


async def test_score_and_confidence_remain_independent(client: AsyncClient) -> None:
    project_id, _ = await create_structured_project(client)
    provider = MockLLMProvider(
        [json.dumps(judge_payload(rating=5, decision="RESEARCH", confidence=0.2))]
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/judge")

    assert response.status_code == 200
    assert response.json()["score"] == 100
    assert response.json()["confidence"] == 0.2
    assert response.json()["decision"] == "RESEARCH"


@pytest.mark.parametrize(
    "payload",
    [
        judge_payload(rating=3, decision="APPROVE", confidence=0.9),
        judge_payload(rating=5, decision="APPROVE", confidence=0.4),
        judge_payload(
            rating=5,
            decision="APPROVE",
            confidence=0.9,
            blockers=["Structural blocker"],
        ),
    ],
)
async def test_invalid_approval_is_retried_and_never_persisted(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
    payload: dict[str, object],
) -> None:
    project_id, _ = await create_structured_project(client)
    provider = MockLLMProvider([json.dumps(payload), json.dumps(payload)])
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/judge")

    assert response.status_code == 502
    async with session_maker() as session:
        judge_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.JUDGE)
                )
            ).all()
        )
        scores = list((await session.scalars(select(ProjectScore))).all())
        decisions = list((await session.scalars(select(DecisionRecord))).all())
    assert len(judge_runs) == 2
    assert all(run.error for run in judge_runs)
    assert scores == []
    assert decisions == []


async def test_judge_requires_structured_project(client: AsyncClient) -> None:
    project = await client.post(
        "/projects", json={"name": "Unstructured", "raw_idea": "A raw idea"}
    )

    response = await client.post(f"/projects/{project.json()['id']}/judge")

    assert response.status_code == 409


async def test_judge_and_history_return_404_for_unknown_project(
    client: AsyncClient,
) -> None:
    project_id = uuid4()

    judge = await client.post(f"/projects/{project_id}/judge")
    scores = await client.get(f"/projects/{project_id}/scores")
    decisions = await client.get(f"/projects/{project_id}/decisions")

    assert judge.status_code == scores.status_code == decisions.status_code == 404


async def test_score_and_decision_history_start_empty(client: AsyncClient) -> None:
    project = await client.post(
        "/projects", json={"name": "New", "raw_idea": "A raw idea"}
    )
    project_id = project.json()["id"]

    scores = await client.get(f"/projects/{project_id}/scores")
    decisions = await client.get(f"/projects/{project_id}/decisions")

    assert scores.json() == []
    assert decisions.json() == []

