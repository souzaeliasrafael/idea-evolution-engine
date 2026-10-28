import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.builder import BuilderAgent
from app.agents.critic import CriticAgent
from app.database.models import AgentRun, Criticism
from app.domain.enums import AgentType
from app.llm.dependencies import get_llm_router
from app.llm.base import LLMResponse
from app.llm.prompts import load_prompt
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.schemas.evaluation import BuilderOutput, CriticOutput


pytestmark = pytest.mark.anyio


def concept_payload(
    *, raw_idea: str = "A raw idea", solution: str = "A bounded workflow."
) -> dict[str, object]:
    return {
        "title": "Structured idea",
        "raw_idea": raw_idea,
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


def builder_concept_payload(
    *, solution: str = "A bounded workflow."
) -> dict[str, object]:
    """Builder concepts omit raw_idea; the server preserves the original one."""
    concept = concept_payload(solution=solution)
    concept.pop("raw_idea")
    return concept


def builder_payload(*, raw_idea: str | None = None) -> dict[str, object]:
    new_concept = builder_concept_payload(
        solution="A focused, bounded product-discovery workflow."
    )
    if raw_idea is not None:
        # Only used to prove that a Builder trying to rewrite raw_idea is rejected.
        new_concept["raw_idea"] = raw_idea
    return {
        "improvements": ["Narrowed the target workflow"],
        "problems_solved": ["Unclear initial scope"],
        "unresolved_problems": ["Willingness to pay"],
        "new_hypotheses": ["Product teams need an explicit evaluation gate"],
        "proposed_changes": ["Focus the MVP on product discovery"],
        "new_concept": new_concept,
    }


def criticism_payload() -> dict[str, object]:
    return {
        "title": "Unproven willingness to pay",
        "severity": "HIGH",
        "claim": "The target users may not pay for a separate evaluation tool.",
        "reason": "The concept contains no purchasing evidence.",
        "affected_hypotheses": ["H-WTP"],
        "evidence_needed": "Pricing interviews with identifiable product teams.",
        "condition_that_refutes_criticism": (
            "At least five target teams commit to a paid pilot."
        ),
    }


async def create_structured_project(client: AsyncClient) -> tuple[str, dict[str, object]]:
    project = await client.post(
        "/projects", json={"name": "Phase 3 project", "raw_idea": "A raw idea"}
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    provider = MockLLMProvider([json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    structured = await client.post(f"/projects/{project_id}/structure")
    assert structured.status_code == 201
    return project_id, structured.json()


async def test_builder_and_critic_schemas_are_strict() -> None:
    invalid_builder = builder_payload()
    invalid_builder["unexpected"] = True
    with pytest.raises(ValidationError):
        BuilderOutput.model_validate(invalid_builder)

    oversized_builder = builder_payload()
    oversized_builder["improvements"] = [f"Change {index}" for index in range(7)]
    with pytest.raises(ValidationError):
        BuilderOutput.model_validate(oversized_builder)

    invalid_critic = {"criticisms": [criticism_payload()]}
    invalid_critic["criticisms"][0]["severity"] = "URGENT"  # type: ignore[index]
    with pytest.raises(ValidationError):
        CriticOutput.model_validate(invalid_critic)


async def test_builder_and_critic_prompts_are_versioned_resources() -> None:
    builder_prompt = load_prompt("builder", "v1")
    critic_prompt = load_prompt("critic", "v1")

    assert "Do not invent evidence" in builder_prompt
    assert "Every criticism must be falsifiable" in critic_prompt


async def test_default_mock_outputs_validate_for_both_agents() -> None:
    provider = MockLLMProvider()

    builder_result = await BuilderAgent(provider, max_attempts=1).run(
        current_concept=concept_payload(), previous_criticisms=[]
    )
    critic_result = await CriticAgent(provider, max_attempts=1).run(
        current_concept=concept_payload()
    )

    # The mock keeps the concept unchanged and never returns raw_idea.
    assert builder_result.output.new_concept.model_dump() == builder_concept_payload()
    assert builder_result.output.unresolved_problems
    assert critic_result.output.criticisms[0].severity.value == "MEDIUM"
    assert [call.role for call in provider.calls] == ["BUILDER", "CRITIC"]


async def test_builder_starts_at_8192_and_recovers_only_missing_fields() -> None:
    complete = builder_payload()
    recovery_values = {
        **{
            key: value
            for key, value in complete.items()
            if key not in {"improvements", "new_concept"}
        },
        **{
            f"new_concept__{key}": value
            for key, value in complete["new_concept"].items()  # type: ignore[union-attr]
            if key != "raw_idea"
        },
    }
    provider = MockLLMProvider(
        [
            LLMResponse(
                content=(
                    '{"improvements":["Narrowed the target workflow"],'
                    '"problems_solved":'
                ),
                model="mock-llm-v1",
                output_tokens=8192,
                finish_reason="max_output_tokens",
            ),
            json.dumps({"values": recovery_values}),
        ]
    )

    result = await BuilderAgent(provider, max_attempts=2).run(
        current_concept=concept_payload(), previous_criticisms=[]
    )

    assert result.output == BuilderOutput.model_validate(complete)
    assert len(result.attempts) == 2
    assert result.attempts[0].error is not None
    assert result.attempts[1].error is None
    assert len(provider.calls) == 2
    assert provider.calls[0].max_output_tokens == 8192
    assert provider.calls[1].max_output_tokens == 4096
    assert "improvements" not in provider.calls[1].input_data["missing_fields"]


@pytest.mark.parametrize("agent_path", ["builder", "critic"])
async def test_agents_require_a_structured_project(
    client: AsyncClient, agent_path: str
) -> None:
    project = await client.post(
        "/projects", json={"name": "Unstructured", "raw_idea": "A raw idea"}
    )
    provider = MockLLMProvider([json.dumps({})])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project.json()['id']}/{agent_path}")

    assert response.status_code == 409
    assert provider.calls == []


async def test_builder_runs_individually_and_creates_child_version(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, v0 = await create_structured_project(client)
    provider = MockLLMProvider([json.dumps(builder_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/builder")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert response.status_code == 200
    assert response.json() == builder_payload()
    assert len(provider.calls) == 1
    assert provider.calls[0].role == "BUILDER"
    assert provider.calls[0].input_data["previous_criticisms"] == []
    assert [version["version"] for version in versions.json()] == [0, 1]
    assert versions.json()[1]["parent_version_id"] == v0["id"]
    assert versions.json()[1]["created_by"] == "BUILDER"
    # The persisted version restores the original raw_idea on the server side.
    assert versions.json()[1]["concept"] == {
        **builder_payload()["new_concept"],
        "raw_idea": "A raw idea",
    }

    async with session_maker() as session:
        builder_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.BUILDER)
                )
            ).all()
        )
        criticisms = list((await session.scalars(select(Criticism))).all())
    assert len(builder_runs) == 1
    assert builder_runs[0].prompt_version == BuilderAgent.prompt_version
    assert criticisms == []


async def test_critic_runs_individually_and_persists_falsifiable_criticism(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, v0 = await create_structured_project(client)
    output = {"criticisms": [criticism_payload()]}
    provider = MockLLMProvider([json.dumps(output)])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/critic")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert response.status_code == 200
    assert response.json() == output
    assert len(provider.calls) == 1
    assert provider.calls[0].role == "CRITIC"
    assert len(versions.json()) == 1

    async with session_maker() as session:
        criticism = await session.scalar(select(Criticism))
        critic_run = await session.scalar(
            select(AgentRun).where(AgentRun.agent == AgentType.CRITIC)
        )
    assert criticism is not None
    assert critic_run is not None
    assert criticism.idea_version_id == v0["id"]
    assert criticism.agent_run_id == critic_run.id
    assert criticism.severity.value == "HIGH"
    assert criticism.condition_that_refutes_criticism == (
        criticism_payload()["condition_that_refutes_criticism"]
    )


async def test_builder_receives_criticisms_for_the_current_version(
    client: AsyncClient,
) -> None:
    project_id, _ = await create_structured_project(client)
    critic_provider = MockLLMProvider(
        [json.dumps({"criticisms": [criticism_payload()]})]
    )
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        critic_provider
    )
    critic_response = await client.post(f"/projects/{project_id}/critic")
    assert critic_response.status_code == 200

    builder_provider = MockLLMProvider([json.dumps(builder_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        builder_provider
    )
    builder_response = await client.post(f"/projects/{project_id}/builder")

    assert builder_response.status_code == 200
    prior = builder_provider.calls[0].input_data["previous_criticisms"]
    assert prior == [criticism_payload()]


async def test_builder_rejects_rewritten_raw_idea_without_creating_version(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ = await create_structured_project(client)
    invalid = builder_payload(raw_idea="A rewritten idea")
    provider = MockLLMProvider([json.dumps(invalid), json.dumps(invalid)])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/builder")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert response.status_code == 502
    assert len(versions.json()) == 1
    async with session_maker() as session:
        failed_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.BUILDER)
                )
            ).all()
        )
    assert len(failed_runs) == 2
    assert all(run.error for run in failed_runs)


async def test_critic_records_exhausted_invalid_outputs(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ = await create_structured_project(client)
    provider = MockLLMProvider(["invalid", json.dumps({"criticisms": [{}]})])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/critic")

    assert response.status_code == 502
    async with session_maker() as session:
        critic_runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.CRITIC)
                )
            ).all()
        )
        criticisms = list((await session.scalars(select(Criticism))).all())
    assert len(critic_runs) == 2
    assert all(run.error for run in critic_runs)
    assert criticisms == []


@pytest.mark.parametrize("agent_path", ["builder", "critic"])
async def test_agents_return_404_for_unknown_project(
    client: AsyncClient, agent_path: str
) -> None:
    response = await client.post(f"/projects/{uuid4()}/{agent_path}")

    assert response.status_code == 404
