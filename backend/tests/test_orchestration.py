import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AgentRun, DecisionRecord, Round
from app.domain.enums import (
    AgentType,
    DecisionType,
    ProjectStatus,
    RoundStatus,
    ScoreCriterion,
)
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.orchestration.rules import (
    require_non_terminal_project,
    validate_round_limit,
)
from app.orchestration.orchestrator import adaptive_agent_plan
from app.orchestration.transitions import TRANSITIONS, transition_for
from app.schemas.project import AgentExecutionPlan
from app.services.errors import ProjectTerminalError, RoundLimitExceededError


pytestmark = pytest.mark.anyio


async def test_adaptive_depth_starts_at_one_and_unlocks_only_needed_agents() -> None:
    configured = AgentExecutionPlan(builder=3, researcher=3, critic=3)

    first_pass = adaptive_agent_plan(
        configured,
        previous_score=None,
        previous_confidence=None,
        enabled=True,
        score_threshold=75,
        confidence_threshold=0.7,
    )
    low_confidence = adaptive_agent_plan(
        configured,
        previous_score=82,
        previous_confidence=0.4,
        enabled=True,
        score_threshold=75,
        confidence_threshold=0.7,
    )

    assert first_pass == AgentExecutionPlan(builder=1, researcher=1, critic=1)
    assert low_confidence == AgentExecutionPlan(builder=1, researcher=3, critic=3)


def concept_payload(*, solution: str = "A bounded workflow.") -> dict[str, object]:
    return {
        "title": "Structured idea",
        "raw_idea": "A raw idea",
        "problem": "Teams build before validating demand.",
        "solution": solution,
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


def builder_concept(concept: dict[str, object]) -> dict[str, object]:
    """Builder concepts omit raw_idea; the server preserves the original one."""
    return {key: value for key, value in concept.items() if key != "raw_idea"}


def builder_payload(round_number: int) -> dict[str, object]:
    return {
        "improvements": [f"Round {round_number} improvement"],
        "problems_solved": [],
        "unresolved_problems": ["Willingness to pay"],
        "new_hypotheses": [],
        "proposed_changes": [f"Create version for round {round_number}"],
        "new_concept": builder_concept(
            concept_payload(solution=f"Concept version {round_number}")
        ),
    }


def critic_payload() -> dict[str, object]:
    return {
        "criticisms": [
            {
                "title": "Demand is unproven",
                "severity": "HIGH",
                "claim": "The target users may not pay.",
                "reason": "No purchasing evidence is available.",
                # A general criticism (no register ID) reaches every Researcher
                # target; one naming specific IDs only reaches matching targets.
                "affected_hypotheses": [],
                "evidence_needed": "Pricing interviews.",
                "condition_that_refutes_criticism": "Five paid pilot commitments.",
            }
        ]
    }


def researcher_payload() -> dict[str, object]:
    return {
        "question": "What evidence supports willingness to pay?",
        "finding": "No ledger evidence currently answers the question.",
        "evidence": [],
        "confidence": 0.1,
        "contradictory_evidence": [],
        "impact_on_project": "The commercial hypothesis remains open.",
        "recommended_action": "Interview five identifiable product teams.",
    }


def judge_payload(
    decision: str, *, rating: int = 3, confidence: float = 0.8
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
        "reasoning_summary": f"Decision: {decision}",
        "critical_blockers": [],
        "most_important_unknowns": ["Demand"],
        "next_actions": [f"Execute {decision}"],
    }


def improver_payload(*, rating: int = 3) -> dict[str, object]:
    return {
        "summary": "Demand evidence is the highest-leverage improvement area.",
        "weaknesses": [
            {
                "criterion": "REAL_PROBLEM",
                "current_rating": rating,
                "cause_type": "EVIDENCE_GAP",
                "diagnosis": "The problem has not been independently validated.",
                "consequence": "The proposal may optimize an unverified need.",
                "confidence_limit": "No direct user evidence is available.",
                "evidence_ids": [],
            }
        ],
        "proposals": [
            {
                "title": "Validate the problem",
                "description": "Interview target teams with a measurable threshold.",
                "target_criteria": ["REAL_PROBLEM"],
                "rationale": "This addresses the weakest evidence gap.",
                "feasibility": 5,
                "expected_impact": 4,
                "effort": "LOW",
                "risks": ["Convenience sampling"],
                "required_evidence": ["Interview records"],
                "validation_step": "Obtain five independent confirmations.",
            }
        ],
        "recommended_strategy": "Validate demand before another broad refinement.",
        "builder_instructions": ["Keep unverified demand claims explicit."],
        "research_questions": ["How intense is the problem for target teams?"],
        "next_steps": ["Gather evidence, then refine."],
        "stop_conditions": ["Stop if target teams do not confirm the problem."],
    }


def round_responses(decision: str, round_number: int) -> list[str]:
    rating = 4 if decision == "APPROVE" else 3
    responses = [
        json.dumps(researcher_payload()),
        json.dumps(builder_payload(round_number)),
        json.dumps(critic_payload()),
        json.dumps(researcher_payload()),
        json.dumps(builder_payload(round_number)),
        json.dumps(judge_payload(decision, rating=rating)),
    ]
    if decision not in {"APPROVE", "DISCARD"}:
        responses.append(json.dumps(improver_payload(rating=rating)))
    return responses


def use_provider(provider: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )


async def create_project(client: AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"name": "Orchestrated", "raw_idea": "A raw idea"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_orchestrator_structures_then_waits_for_human_approval(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(
        [json.dumps(concept_payload()), *round_responses("APPROVE", 1)],
        model_name="workflow-model",
    )
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 3}
    )
    project = await client.get(f"/projects/{project_id}")
    rounds = await client.get(f"/projects/{project_id}/rounds")
    decisions = await client.get(f"/projects/{project_id}/decisions")
    second_run = await client.post(f"/projects/{project_id}/run")

    assert response.status_code == 200
    assert response.json()["project_status"] == "AWAITING_CONFIRMATION"
    assert response.json()["stop_reason"] == "AWAITING_CONFIRMATION"
    assert response.json()["final_decision"] == "APPROVE"
    assert response.json()["final_score"] == 80
    assert project.json()["status"] == "AWAITING_CONFIRMATION"
    assert rounds.status_code == 200
    assert rounds.json()[0]["status"] == "COMPLETED"
    assert rounds.json()[0]["round_number"] == 1
    assert second_run.status_code == 409
    assert decisions.json()[0]["human_review_status"] == "PENDING"
    assert [call.role for call in provider.calls] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
        "CRITIC",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
    ]
    judge_input = provider.calls[6].input_data
    assert judge_input["hypotheses"]
    assert judge_input["latest_research"]["question"] == researcher_payload()["question"]

    round_id = rounds.json()[0]["id"]
    async with session_maker() as session:
        runs = list((await session.scalars(select(AgentRun))).all())
        decision = await session.scalar(select(DecisionRecord))
    assert runs[0].agent == AgentType.STRUCTURER and runs[0].round_id is None
    assert {run.round_id for run in runs[1:]} == {round_id}
    assert decision is not None and decision.round_number == 1

    reviewed = await client.post(
        f"/projects/{project_id}/decisions/{decision.id}/review",
        json={"action": "ACCEPT_RECOMMENDATION", "note": "Human approval"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "APPROVED"


async def test_default_run_is_bounded_to_three_rounds_and_links_versions(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(
        [
            json.dumps(concept_payload()),
            *round_responses("REFINE", 1),
            *round_responses("REFINE", 2),
            *round_responses("REFINE", 3),
        ]
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/run")
    versions = await client.get(f"/projects/{project_id}/versions")
    decisions = await client.get(f"/projects/{project_id}/decisions")

    assert response.status_code == 200
    assert response.json()["stop_reason"] == "MAX_ROUNDS_REACHED"
    assert [item["round_number"] for item in response.json()["rounds"]] == [1, 2, 3]
    assert [item["version"] for item in versions.json()] == list(range(7))
    assert decisions.json()[0]["to_version_id"] == versions.json()[4]["id"]
    assert decisions.json()[1]["to_version_id"] == versions.json()[6]["id"]
    assert decisions.json()[2]["to_version_id"] is None
    builder_calls = [call for call in provider.calls if call.role == "BUILDER"]
    assert builder_calls[0].input_data["workflow_instruction"] is None
    assert builder_calls[2].input_data["workflow_instruction"]["decision"] == "REFINE"
    assert len(provider.calls) == 22

    resume_provider = MockLLMProvider(round_responses("APPROVE", 4))
    use_provider(resume_provider)
    resumed = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    resumed_rounds = await client.get(f"/projects/{project_id}/rounds")
    resumed_versions = await client.get(f"/projects/{project_id}/versions")
    resumed_decisions = await client.get(f"/projects/{project_id}/decisions")

    assert resumed.status_code == 200
    assert resumed.json()["rounds"][0]["round_number"] == 4
    assert resumed.json()["project_status"] == "AWAITING_CONFIRMATION"
    assert [item["round_number"] for item in resumed_rounds.json()] == [1, 2, 3, 4]
    resume_builder_calls = [
        call for call in resume_provider.calls if call.role == "BUILDER"
    ]
    instruction = resume_builder_calls[0].input_data["workflow_instruction"]
    assert instruction["decision"] == "REFINE"
    assert (
        resumed_decisions.json()[2]["to_version_id"]
        == resumed_versions.json()[8]["id"]
    )


async def test_next_round_context_is_audited_consumed_and_sent_with_prior_state(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    first_provider = MockLLMProvider(
        [json.dumps(concept_payload()), *round_responses("REFINE", 1)]
    )
    use_provider(first_provider)
    first = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    assert first.status_code == 200

    guidance = "Priorize operação offline e custos para pequenos clientes."
    saved = await client.patch(
        f"/projects/{project_id}/next-round-context",
        json={"next_round_context": guidance},
    )
    assert saved.status_code == 200

    second_provider = MockLLMProvider(round_responses("APPROVE", 2))
    use_provider(second_provider)
    second = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    project = await client.get(f"/projects/{project_id}")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert second.status_code == 200
    assert project.json()["next_round_context"] is None
    assert rounds.json()[0]["human_context"] is None
    assert rounds.json()[1]["human_context"] == guidance
    assert [call.role for call in second_provider.calls] == [
        "RESEARCHER",
        "BUILDER",
        "CRITIC",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
    ]
    for call in second_provider.calls:
        assert call.input_data["user_context"] == guidance

    researcher_input = second_provider.calls[0].input_data
    builder_input = second_provider.calls[1].input_data
    second_researcher_input = second_provider.calls[3].input_data
    judge_input = second_provider.calls[5].input_data
    assert builder_input["current_concept"]["solution"] == "Concept version 1"
    assert builder_input["previous_criticisms"]
    assert researcher_input["hypotheses"]
    assert researcher_input["criticisms"]
    assert builder_input["accumulated_context"]["events"][0]["agent"] == "RESEARCHER"
    assert second_researcher_input["workflow_stage"] == "CRITIC_VERIFICATION"
    assert len(judge_input["accumulated_context"]["events"]) == 5
    assert judge_input["previous_scores"]
    assert judge_input["previous_decisions"]


async def test_agent_plan_controls_optional_agents_per_round(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects",
        json={
            "name": "Focused orchestration",
            "raw_idea": "A raw idea",
            "agent_plan": {"builder": 2, "researcher": 3, "critic": 0},
        },
    )
    project_id = created.json()["id"]
    provider = MockLLMProvider(
        [
            json.dumps(concept_payload()),
            json.dumps(researcher_payload()),
            json.dumps(builder_payload(1)),
            json.dumps(researcher_payload()),
            json.dumps(builder_payload(2)),
            json.dumps(judge_payload("APPROVE", rating=4)),
        ]
    )
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    versions = await client.get(f"/projects/{project_id}/versions")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert response.status_code == 200, (
        response.text,
        [call.role for call in provider.calls],
        rounds.json(),
    )
    assert [call.role for call in provider.calls] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
    ]
    assert [item["version"] for item in versions.json()] == [0, 1, 2]
    assert response.json()["rounds"][0]["resulting_version_id"] == versions.json()[2]["id"]


async def test_research_decision_continues_with_researcher_until_round_limit(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider()
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 5}
    )

    assert response.status_code == 200
    assert response.json()["final_decision"] == "RESEARCH"
    assert response.json()["project_status"] == "RESEARCHING"
    assert response.json()["stop_reason"] == "MAX_ROUNDS_REACHED"
    assert len(response.json()["rounds"]) == 5
    assert [call.role for call in provider.calls[:7]] == [
        "STRUCTURER",
        "RESEARCHER",
        "BUILDER",
        "CRITIC",
        "RESEARCHER",
        "BUILDER",
        "JUDGE",
    ]
    assert len(provider.calls) == 36


async def test_pivot_requires_review_then_test_creates_experiment(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(
        [
            json.dumps(concept_payload()),
            *round_responses("PIVOT", 1),
            *round_responses("TEST", 2),
        ]
    )
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 5}
    )

    assert response.status_code == 200
    assert response.json()["final_decision"] == "PIVOT"
    assert response.json()["project_status"] == "AWAITING_CONFIRMATION"
    assert response.json()["stop_reason"] == "AWAITING_CONFIRMATION"
    decisions = await client.get(f"/projects/{project_id}/decisions")
    reviewed = await client.post(
        f"/projects/{project_id}/decisions/{decisions.json()[0]['id']}/review",
        json={"action": "ACCEPT_RECOMMENDATION"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "PIVOTING"

    resumed = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 5}
    )
    experiments = await client.get(f"/projects/{project_id}/experiments")

    assert resumed.status_code == 200
    assert resumed.json()["final_decision"] == "TEST"
    assert resumed.json()["project_status"] == "VALIDATING"
    assert resumed.json()["stop_reason"] == "AWAITING_TEST"
    assert len(resumed.json()["rounds"]) == 1
    assert len(experiments.json()) == 1
    assert experiments.json()[0]["status"] == "PLANNED"
    builder_calls = [call for call in provider.calls if call.role == "BUILDER"]
    assert builder_calls[2].input_data["workflow_instruction"]["decision"] == "PIVOT"


async def test_manual_pivot_and_continue_anyway_are_explicit_human_overrides(
    client: AsyncClient,
) -> None:
    pivot_project_id = await create_project(client)
    pivot_provider = MockLLMProvider(
        [
            json.dumps(concept_payload()),
            *round_responses("APPROVE", 1),
            *round_responses("RESEARCH", 2),
        ]
    )
    use_provider(pivot_provider)
    await client.post(
        f"/projects/{pivot_project_id}/run", json={"max_rounds": 1}
    )
    pivot_decisions = await client.get(
        f"/projects/{pivot_project_id}/decisions"
    )
    reviewed_pivot = await client.post(
        f"/projects/{pivot_project_id}/decisions/{pivot_decisions.json()[0]['id']}/review",
        json={
            "action": "MANUAL_PIVOT",
            "note": "Serve regulated clinics instead of generic product teams.",
        },
    )
    assert reviewed_pivot.status_code == 200
    assert reviewed_pivot.json()["status"] == "PIVOTING"

    resumed = await client.post(
        f"/projects/{pivot_project_id}/run", json={"max_rounds": 1}
    )
    assert resumed.status_code == 200
    builder_calls = [call for call in pivot_provider.calls if call.role == "BUILDER"]
    assert builder_calls[-1].input_data["workflow_instruction"]["decision"] == "PIVOT"
    assert "regulated clinics" in builder_calls[-1].input_data[
        "workflow_instruction"
    ]["human_instruction"]

    continue_project_id = await create_project(client)
    continue_provider = MockLLMProvider(
        [json.dumps(concept_payload()), *round_responses("DISCARD", 1)]
    )
    use_provider(continue_provider)
    await client.post(
        f"/projects/{continue_project_id}/run", json={"max_rounds": 1}
    )
    continue_decisions = await client.get(
        f"/projects/{continue_project_id}/decisions"
    )
    continued = await client.post(
        f"/projects/{continue_project_id}/decisions/{continue_decisions.json()[0]['id']}/review",
        json={"action": "CONTINUE_ANYWAY", "note": "Collect more evidence."},
    )
    assert continued.status_code == 200
    assert continued.json()["status"] == "DEBATING"


async def test_configured_round_ceiling_rejects_request_before_llm_calls(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider()
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 6}
    )

    assert response.status_code == 422
    assert "configured maximum is 5" in response.json()["detail"]
    assert provider.calls == []


async def test_recoverable_agent_failure_warns_and_preserves_audit_runs(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(
        [json.dumps(concept_payload()), "not-json", "still-not-json"]
    )
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert response.status_code == 200
    assert rounds.json()[0]["status"] == "COMPLETED"
    assert "Recovered agent failures" in rounds.json()[0]["error"]
    async with session_maker() as session:
        failed_round = await session.scalar(select(Round))
        researcher_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.RESEARCHER)
                )
            ).all()
        )
    assert failed_round is not None and failed_round.status == RoundStatus.COMPLETED
    assert len(researcher_runs) == 3
    assert {run.round_id for run in researcher_runs} == {failed_round.id}
    assert sum(run.error is not None for run in researcher_runs) == 2
    assert sum(run.error is None for run in researcher_runs) == 1


async def test_structurer_failure_restores_status_without_opening_a_round(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(["not-json", "still-not-json"])
    use_provider(provider)

    response = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    project = await client.get(f"/projects/{project_id}")
    rounds = await client.get(f"/projects/{project_id}/rounds")

    assert response.status_code == 502
    assert project.json()["status"] == "DRAFT"
    assert rounds.json() == []
    async with session_maker() as session:
        structurer_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.STRUCTURER)
                )
            ).all()
        )
    assert len(structurer_runs) == 2
    assert all(run.round_id is None and run.error for run in structurer_runs)


async def test_round_listing_returns_404_for_unknown_project(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/projects/{uuid4()}/rounds")

    assert response.status_code == 404


async def test_running_round_blocks_a_second_orchestrator(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    structure_provider = MockLLMProvider([json.dumps(concept_payload())])
    use_provider(structure_provider)
    structured = await client.post(f"/projects/{project_id}/structure")
    assert structured.status_code == 201

    async with session_maker() as session:
        session.add(
            Round(
                project_id=project_id,
                round_number=1,
                status=RoundStatus.RUNNING,
                starting_version_id=structured.json()["id"],
            )
        )
        await session.commit()

    provider = MockLLMProvider()
    use_provider(provider)
    response = await client.post(f"/projects/{project_id}/run")

    assert response.status_code == 409
    assert provider.calls == []


def test_transition_table_and_orchestration_rules_are_explicit() -> None:
    assert set(TRANSITIONS) == set(DecisionType)
    assert transition_for(DecisionType.REFINE).continue_run is True
    assert (
        transition_for(DecisionType.PIVOT).project_status
        == ProjectStatus.AWAITING_CONFIRMATION
    )
    assert transition_for(DecisionType.RESEARCH).continue_run is True
    assert transition_for(DecisionType.TEST).project_status == ProjectStatus.VALIDATING
    assert (
        transition_for(DecisionType.APPROVE).project_status
        == ProjectStatus.AWAITING_CONFIRMATION
    )
    assert (
        transition_for(DecisionType.DISCARD).project_status
        == ProjectStatus.AWAITING_CONFIRMATION
    )
    validate_round_limit(5, 5)
    with pytest.raises(RoundLimitExceededError):
        validate_round_limit(6, 5)
    with pytest.raises(ProjectTerminalError):
        require_non_terminal_project(ProjectStatus.APPROVED)
