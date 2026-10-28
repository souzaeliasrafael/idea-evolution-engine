import asyncio
import json
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.domain.enums import ScoreCriterion
from app.llm.base import LLMResponse
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.orchestration.stagnation import StagnationDetector


pytestmark = pytest.mark.anyio


class PausingBudgetProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__(
            [
                costed(concept_payload(), "0.100000"),
                costed(researcher_payload(), "0.100000"),
            ]
        )
        self.researcher_started = asyncio.Event()
        self.release_researcher = asyncio.Event()
        self._paused = False

    async def generate(self, request):
        if request.role == "RESEARCHER" and not self._paused:
            self._paused = True
            self.researcher_started.set()
            await self.release_researcher.wait()
        return await super().generate(request)


def concept_payload() -> dict[str, object]:
    return {
        "title": "Budgeted idea",
        "raw_idea": "A raw idea",
        "problem": "Teams spend without a validation boundary.",
        "solution": "A bounded evaluation workflow.",
        "target_users": ["Product teams"],
        "value_proposition": "Cap discovery spend.",
        "possible_use_cases": ["Product discovery"],
        "business_models": ["Subscription"],
        "technical_assumptions": ["Typed outputs are reliable"],
        "business_assumptions": ["Teams value budget controls"],
        "unknowns": ["Demand"],
        "risks": ["Weak differentiation"],
        "initial_mvp": "Evaluate one idea.",
    }


def builder_concept(concept: dict[str, object]) -> dict[str, object]:
    """Builder concepts omit raw_idea; the server preserves the original one."""
    return {key: value for key, value in concept.items() if key != "raw_idea"}


def builder_payload() -> dict[str, object]:
    return {
        "improvements": ["Focused scope"],
        "problems_solved": [],
        "unresolved_problems": ["Demand"],
        "new_hypotheses": [],
        "proposed_changes": ["Focus scope"],
        "new_concept": builder_concept(concept_payload()),
    }


def researcher_payload() -> dict[str, object]:
    return {
        "question": "What evidence is needed?",
        "finding": "Evidence remains incomplete.",
        "evidence": [],
        "confidence": 0.1,
        "contradictory_evidence": [],
        "impact_on_project": "Demand remains open.",
        "recommended_action": "Gather evidence.",
    }


def judge_payload(decision: str = "RESEARCH") -> dict[str, object]:
    return {
        "decision": decision,
        "criteria": [
            {
                "criterion": criterion.value,
                "rating": 3,
                "rationale": "Evidence remains inconclusive.",
                "evidence_ids": [],
            }
            for criterion in ScoreCriterion
        ],
        "confidence": 0.4,
        "reasoning_summary": "More validation is needed.",
        "critical_blockers": [],
        "most_important_unknowns": ["Demand"],
        "next_actions": ["Gather evidence"],
    }


def costed(payload: dict[str, object], cost: str) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(payload),
        model="costed-mock",
        input_tokens=10,
        output_tokens=20,
        estimated_cost=Decimal(cost),
    )


def use_provider(provider: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )


async def create_project(client: AsyncClient, budget: str | None = None) -> str:
    payload: dict[str, object] = {"name": "Budgeted", "raw_idea": "A raw idea"}
    if budget is not None:
        payload["max_ai_budget"] = budget
    response = await client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def structure(client: AsyncClient, project_id: str, cost: str = "0") -> None:
    provider = MockLLMProvider([costed(concept_payload(), cost)])
    use_provider(provider)
    response = await client.post(f"/projects/{project_id}/structure")
    assert response.status_code == 201


def test_stagnation_requires_three_consecutive_small_improvements() -> None:
    assert StagnationDetector.detect([60, 62, 64]) is False
    assert StagnationDetector.detect([60, 62, 64, 66]) is True
    assert StagnationDetector.detect([60, 62, 66, 68]) is False
    assert StagnationDetector.detect([70, 69, 68, 67]) is True


async def test_agent_costs_accumulate_and_exhausted_budget_blocks_next_call(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client, "0.500000")
    await structure(client, project_id, "0.300000")
    provider = MockLLMProvider([costed(builder_payload(), "0.250000")])
    use_provider(provider)

    built = await client.post(f"/projects/{project_id}/builder")
    project = await client.get(f"/projects/{project_id}")
    blocked = await client.post(f"/projects/{project_id}/critic")

    assert built.status_code == 200
    assert project.json()["total_cost"] == "0.550000"
    assert project.json()["remaining_ai_budget"] == "0"
    assert project.json()["budget_exhausted"] is True
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Project AI budget is exhausted"
    assert len(provider.calls) == 1


async def test_failed_attempt_cost_is_also_accounted(client: AsyncClient) -> None:
    project_id = await create_project(client, "1.000000")
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="not-json",
                model="costed-mock",
                estimated_cost=Decimal("0.200000"),
            ),
            costed(concept_payload(), "0.100000"),
        ]
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/structure")
    project = await client.get(f"/projects/{project_id}")

    assert response.status_code == 201
    assert project.json()["total_cost"] == "0.300000"


async def test_orchestrator_stops_mid_round_before_starting_next_agent(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client, "0.500000")
    provider = MockLLMProvider(
        [
            costed(concept_payload(), "0.100000"),
            costed(researcher_payload(), "0.100000"),
            costed(builder_payload(), "0.500000"),
        ]
    )
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stop_reason"] == "BUDGET_LIMIT_REACHED"
    assert body["final_decision"] is None
    assert body["final_score"] is None
    assert body["rounds"][0]["status"] == "COMPLETED"
    assert body["rounds"][0]["budget_limit_reached"] is True
    assert body["rounds"][0]["resulting_version_id"] is not None
    assert [call.role for call in provider.calls] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
    ]


async def test_increased_budget_is_reloaded_before_the_next_agent(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client, "0.150000")
    provider = PausingBudgetProvider()
    use_provider(provider)

    run_task = asyncio.create_task(
        client.post(f"/projects/{project_id}/run", json={"max_rounds": 1})
    )
    try:
        await asyncio.wait_for(provider.researcher_started.wait(), timeout=2)
        updated = await client.patch(
            f"/projects/{project_id}/budget",
            json={"max_ai_budget": "1.000000"},
        )
    finally:
        provider.release_researcher.set()

    run = await run_task

    assert updated.status_code == 200
    assert updated.json()["max_ai_budget"] == "1.000000"
    assert run.status_code == 200
    assert run.json()["stop_reason"] == "MAX_ROUNDS_REACHED"
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


async def test_unlimited_project_continues_with_zero_cost_mock(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider()
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )

    assert response.status_code == 200
    assert response.json()["stop_reason"] == "MAX_ROUNDS_REACHED"
    assert len(provider.calls) == 8


async def test_four_flat_judgments_mark_stagnation_and_refine_is_rejected(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    await structure(client, project_id)

    for _ in range(4):
        provider = MockLLMProvider([json.dumps(judge_payload())])
        use_provider(provider)
        response = await client.post(f"/projects/{project_id}/judge")
        assert response.status_code == 200

    project = await client.get(f"/projects/{project_id}")
    assert project.json()["stagnation_detected"] is True

    invalid = json.dumps(judge_payload("REFINE"))
    provider = MockLLMProvider([invalid, invalid])
    use_provider(provider)
    response = await client.post(f"/projects/{project_id}/judge")

    assert response.status_code == 502
    assert len(provider.calls) == 2
    assert provider.calls[0].input_data["stagnation_detected"] is True
