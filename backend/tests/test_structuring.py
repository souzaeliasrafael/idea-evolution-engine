import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    AgentRun,
    IdeaVersion,
    ImmutableIdeaVersionError,
)
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.schemas.idea import IdeaConcept


pytestmark = pytest.mark.anyio


def concept_payload(raw_idea: str = "A raw idea") -> dict[str, object]:
    return {
        "title": "Structured idea",
        "raw_idea": raw_idea,
        "problem": "Teams build before validating demand.",
        "solution": "A bounded idea-evaluation workflow.",
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


async def create_project(client: AsyncClient, raw_idea: str = "A raw idea") -> str:
    response = await client.post(
        "/projects", json={"name": "Structured project", "raw_idea": raw_idea}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_idea_concept_rejects_missing_and_extra_fields() -> None:
    missing_title = concept_payload()
    del missing_title["title"]
    with pytest.raises(ValidationError):
        IdeaConcept.model_validate(missing_title)

    extra_field = concept_payload()
    extra_field["score"] = 100
    with pytest.raises(ValidationError):
        IdeaConcept.model_validate(extra_field)


async def test_structure_project_creates_v0_and_agent_run(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider([json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/structure")

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == project_id
    assert body["version"] == 0
    assert body["parent_version_id"] is None
    assert body["created_by"] == "STRUCTURER"
    assert body["concept"] == concept_payload()
    assert len(provider.calls) == 1
    assert provider.calls[0].role == "STRUCTURER"

    async with session_maker() as session:
        runs = list((await session.scalars(select(AgentRun))).all())
    assert len(runs) == 1
    assert runs[0].prompt_version == "v1"
    assert runs[0].model == "mock-llm-v1"
    assert runs[0].error is None


async def test_versions_endpoint_returns_persisted_v0(client: AsyncClient) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider([json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    created = await client.post(f"/projects/{project_id}/structure")

    response = await client.get(f"/projects/{project_id}/versions")

    assert created.status_code == 201
    assert response.status_code == 200
    assert response.json() == [created.json()]


async def test_structurer_retries_invalid_json_then_recovers(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider(["not-json", json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/structure")

    assert response.status_code == 201
    assert len(provider.calls) == 2
    async with session_maker() as session:
        runs = list(
            (
                await session.scalars(
                    select(AgentRun).order_by(AgentRun.created_at, AgentRun.id)
                )
            ).all()
        )
    assert len(runs) == 2
    assert sum(run.error is not None for run in runs) == 1
    assert sum(run.error is None for run in runs) == 1
    failed_run = next(run for run in runs if run.error is not None)
    successful_run = next(run for run in runs if run.error is None)
    assert failed_run.output_json == {"raw_response": "not-json"}
    assert successful_run.output_json == concept_payload()


async def test_structurer_records_failure_and_stops_safely(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider([RuntimeError("offline"), "still invalid"])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/structure")

    assert response.status_code == 502
    assert len(provider.calls) == 2
    versions = await client.get(f"/projects/{project_id}/versions")
    assert versions.json() == []
    async with session_maker() as session:
        runs = list((await session.scalars(select(AgentRun))).all())
    assert len(runs) == 2
    assert all(run.error for run in runs)


async def test_structurer_must_preserve_raw_idea(client: AsyncClient) -> None:
    project_id = await create_project(client, raw_idea="Original text")
    altered = concept_payload(raw_idea="Rewritten text")
    provider = MockLLMProvider([json.dumps(altered), json.dumps(altered)])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )

    response = await client.post(f"/projects/{project_id}/structure")

    assert response.status_code == 502


async def test_project_can_only_be_initially_structured_once(client: AsyncClient) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider([json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    first = await client.post(f"/projects/{project_id}/structure")

    second = await client.post(f"/projects/{project_id}/structure")

    assert first.status_code == 201
    assert second.status_code == 409
    assert len(provider.calls) == 1


async def test_idea_version_is_immutable(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_project(client)
    provider = MockLLMProvider([json.dumps(concept_payload())])
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    response = await client.post(f"/projects/{project_id}/structure")
    assert response.status_code == 201

    async with session_maker() as session:
        version = await session.scalar(select(IdeaVersion))
        assert version is not None
        version.reason_for_change = "Attempted mutation"
        with pytest.raises(ImmutableIdeaVersionError):
            await session.commit()
        await session.rollback()


async def test_structure_and_versions_return_404_for_unknown_project(
    client: AsyncClient,
) -> None:
    project_id = uuid4()

    structure = await client.post(f"/projects/{project_id}/structure")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert structure.status_code == 404
    assert versions.status_code == 404
