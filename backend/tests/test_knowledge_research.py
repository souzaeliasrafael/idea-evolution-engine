import json
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AgentRun
from app.domain.enums import AgentType
from app.llm.base import LLMResponse, WebSource
from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.schemas.knowledge import EvidenceCreate, HypothesisCreate
from app.schemas.research import ResearcherOutput


pytestmark = pytest.mark.anyio


def concept_payload() -> dict[str, object]:
    return {
        "title": "Structured idea",
        "raw_idea": "A raw idea",
        "problem": "Teams build before validating demand.",
        "solution": "A bounded workflow.",
        "target_users": ["Product teams"],
        "value_proposition": "Reduce waste before implementation.",
        "possible_use_cases": ["Product discovery"],
        "business_models": ["Subscription"],
        "technical_assumptions": ["LLMs can return typed JSON"],
        "business_assumptions": ["Teams will pay for risk reduction"],
        "unknowns": ["Willingness to pay"],
        "risks": ["Low differentiation"],
        "initial_mvp": "Evaluate one idea with a bounded workflow.",
    }


def builder_payload() -> dict[str, object]:
    return {
        "improvements": ["Narrowed the workflow"],
        "problems_solved": [],
        "unresolved_problems": ["Demand"],
        "new_hypotheses": ["Product teams will complete a weekly evaluation"],
        "proposed_changes": ["Focus on product teams"],
        "new_concept": concept_payload(),
    }


def researcher_payload(
    *,
    evidence: list[str] | None = None,
    contradictory: list[str] | None = None,
    confidence: float = 0.1,
) -> dict[str, object]:
    return {
        "question": "Will product teams pay for risk reduction?",
        "finding": "The ledger is not yet conclusive.",
        "evidence": evidence or [],
        "confidence": confidence,
        "contradictory_evidence": contradictory or [],
        "impact_on_project": "Commercial viability remains uncertain.",
        "recommended_action": "Interview five product teams.",
    }


def use_provider(provider: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )


async def create_project(client: AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"name": "Knowledge project", "raw_idea": "A raw idea"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def create_structured_project(client: AsyncClient) -> str:
    project_id = await create_project(client)
    use_provider(MockLLMProvider([json.dumps(concept_payload())]))
    response = await client.post(f"/projects/{project_id}/structure")
    assert response.status_code == 201
    return project_id


def test_knowledge_and_research_schemas_enforce_ranges_and_ids() -> None:
    with pytest.raises(ValidationError):
        HypothesisCreate(
            statement="Out-of-range impact",
            category="BUSINESS",
            impact=11,
            confidence=0.5,
        )
    with pytest.raises(ValidationError):
        EvidenceCreate(
            hypothesis_id="not-an-id",
            source="Interview",
            source_type="INTERVIEW",
            claim="A claim",
            direction="SUPPORT",
            strength=3,
        )
    with pytest.raises(ValidationError):
        ResearcherOutput.model_validate(researcher_payload(confidence=1.1))


async def test_structurer_populates_prioritized_hypothesis_register(
    client: AsyncClient,
) -> None:
    project_id = await create_structured_project(client)

    response = await client.get(f"/projects/{project_id}/hypotheses")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["H001", "H002", "H003"]
    assert {item["category"] for item in response.json()} == {
        "TECHNICAL",
        "BUSINESS",
        "UNKNOWN",
    }
    assert all(item["priority"] == 5.0 for item in response.json())
    assert response.json()[0]["origin"] == "STRUCTURER"
    classifications = {item["epistemic_classification"] for item in response.json()}
    assert classifications == {"ASSUMPTION", "UNKNOWN"}


async def test_manual_hypothesis_and_evidence_are_traceable(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)
    hypothesis_payload = {
        "statement": "Ten teams will commit to a paid pilot",
        "category": "MARKET",
        "impact": 10,
        "confidence": 0.2,
        "status": "OPEN",
        "epistemic_classification": "ASSUMPTION",
    }

    hypothesis = await client.post(
        f"/projects/{project_id}/hypotheses", json=hypothesis_payload
    )
    duplicate = await client.post(
        f"/projects/{project_id}/hypotheses",
        json={**hypothesis_payload, "statement": hypothesis_payload["statement"].upper()},
    )
    evidence = await client.post(
        f"/projects/{project_id}/evidence",
        json={
            "hypothesis_id": "H001",
            "source": "Pilot commitment interviews",
            "source_type": "INTERVIEW",
            "claim": "Three of five teams signed a letter of intent.",
            "direction": "SUPPORT",
            "strength": 3,
            "epistemic_classification": "FACT",
            "url": "",
            "date": "2026-09-15",
        },
    )
    hypotheses = await client.get(f"/projects/{project_id}/hypotheses")
    evidence_list = await client.get(f"/projects/{project_id}/evidence")
    updated = await client.patch(
        f"/projects/{project_id}/hypotheses/H001",
        json={"confidence": 0.8, "status": "PARTIAL"},
    )

    assert hypothesis.status_code == 201
    assert hypothesis.json()["id"] == "H001"
    assert hypothesis.json()["priority"] == 8.0
    assert duplicate.status_code == 409
    assert evidence.status_code == 201
    assert evidence.json()["id"] == "E001"
    assert evidence.json()["hypothesis_id"] == "H001"
    assert evidence.json()["origin"] == "USER"
    assert hypotheses.json()[0]["evidence_ids"] == ["E001"]
    assert evidence_list.json() == [evidence.json()]
    assert updated.status_code == 200
    assert updated.json()["priority"] == 2.0
    assert updated.json()["status"] == "PARTIAL"
    assert updated.json()["evidence_ids"] == ["E001"]


async def test_evidence_rejects_unknown_hypothesis(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(
        f"/projects/{project_id}/evidence",
        json={
            "hypothesis_id": "H999",
            "source": "Interview",
            "source_type": "INTERVIEW",
            "claim": "A claim",
            "direction": "NEUTRAL",
            "strength": 1,
        },
    )

    assert response.status_code == 404
    missing_update = await client.patch(
        f"/projects/{project_id}/hypotheses/H999", json={"confidence": 0.5}
    )
    empty_update = await client.patch(
        f"/projects/{project_id}/hypotheses/H001", json={}
    )
    null_update = await client.patch(
        f"/projects/{project_id}/hypotheses/H001", json={"confidence": None}
    )
    assert missing_update.status_code == 404
    assert empty_update.status_code == 422
    assert null_update.status_code == 422


async def test_builder_registers_only_new_hypotheses(client: AsyncClient) -> None:
    project_id = await create_structured_project(client)
    use_provider(MockLLMProvider([json.dumps(builder_payload())]))

    response = await client.post(f"/projects/{project_id}/builder")
    hypotheses = await client.get(f"/projects/{project_id}/hypotheses")

    assert response.status_code == 200
    assert len(hypotheses.json()) == 4
    created = next(
        item
        for item in hypotheses.json()
        if item["statement"] == "Product teams will complete a weekly evaluation"
    )
    assert created["origin"] == "BUILDER"


async def test_researcher_cites_only_ledger_evidence_and_persists_run(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_structured_project(client)
    for direction, claim in [
        ("SUPPORT", "Three teams want a pilot."),
        ("CONTRADICT", "Two teams use an existing alternative."),
    ]:
        response = await client.post(
            f"/projects/{project_id}/evidence",
            json={
                "hypothesis_id": "H002",
                "source": f"Interview {direction}",
                "source_type": "INTERVIEW",
                "claim": claim,
                "direction": direction,
                "strength": 3,
                "epistemic_classification": "FACT",
            },
        )
        assert response.status_code == 201
    provider = MockLLMProvider(
        [
            json.dumps(
                researcher_payload(
                    evidence=["E001"],
                    contradictory=["E002"],
                    confidence=0.7,
                )
            )
        ],
        model_name="research-model",
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/researcher")
    versions = await client.get(f"/projects/{project_id}/versions")

    assert response.status_code == 200
    assert response.json()["evidence"] == ["E001"]
    assert response.json()["contradictory_evidence"] == ["E002"]
    assert provider.calls[0].role == "RESEARCHER"
    assert [item["id"] for item in provider.calls[0].input_data["evidence"]] == [
        "E001",
        "E002",
    ]
    assert len(versions.json()) == 1
    async with session_maker() as session:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.agent == AgentType.RESEARCHER)
        )
    assert run is not None
    assert run.model == "research-model"
    assert run.round_id is None


async def test_researcher_retries_unknown_or_misclassified_evidence_ids(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await create_structured_project(client)
    invalid = researcher_payload(evidence=["E999"], confidence=0.8)
    provider = MockLLMProvider([json.dumps(invalid), json.dumps(invalid)])
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/researcher")

    assert response.status_code == 502
    async with session_maker() as session:
        runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.agent == AgentType.RESEARCHER)
                )
            ).all()
        )
    assert len(runs) == 2
    assert all(run.error and "unknown evidence IDs" in run.error for run in runs)


async def test_researcher_rejects_supporting_evidence_as_contradictory(
    client: AsyncClient,
) -> None:
    project_id = await create_structured_project(client)
    evidence = await client.post(
        f"/projects/{project_id}/evidence",
        json={
            "hypothesis_id": "H002",
            "source": "Interview",
            "source_type": "INTERVIEW",
            "claim": "A team wants a pilot.",
            "direction": "SUPPORT",
            "strength": 2,
        },
    )
    assert evidence.status_code == 201
    invalid = researcher_payload(contradictory=["E001"], confidence=0.7)
    provider = MockLLMProvider([json.dumps(invalid), json.dumps(invalid)])
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/researcher")

    assert response.status_code == 502
    assert len(provider.calls) == 2


async def test_offline_mock_returns_plan_without_inventing_evidence(
    client: AsyncClient,
) -> None:
    project_id = await create_structured_project(client)
    provider = MockLLMProvider()
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/researcher")

    assert response.status_code == 200
    assert response.json()["evidence"] == []
    assert response.json()["contradictory_evidence"] == []
    assert response.json()["confidence"] == 0.0
    assert "add" in response.json()["recommended_action"].lower()


async def test_web_research_registers_sources_and_observability(
    client: AsyncClient,
) -> None:
    project_id = await create_structured_project(client)

    class WebMockProvider(MockLLMProvider):
        @property
        def supports_web_search(self) -> bool:
            return True

    provider = WebMockProvider(
        [
            LLMResponse(
                content=json.dumps(researcher_payload(confidence=0.7)),
                model="web-research-model",
                input_tokens=100,
                output_tokens=50,
                web_search_calls=1,
                tool_cost=Decimal("0.01"),
                web_sources=(
                    WebSource(
                        url="https://example.com/primary-report",
                        title="Primary report",
                    ),
                ),
                estimated_cost=Decimal("0.0107"),
            )
        ]
    )
    use_provider(provider)

    response = await client.post(f"/projects/{project_id}/researcher")
    evidence = await client.get(f"/projects/{project_id}/evidence")
    timeline = await client.get(f"/projects/{project_id}/timeline")

    assert response.status_code == 200
    assert response.json()["evidence"] == ["E001"]
    assert provider.calls[0].web_search is not None
    assert provider.calls[0].web_search.max_calls == 2
    assert evidence.json()[0]["url"] == "https://example.com/primary-report"
    assert evidence.json()[0]["origin"] == "RESEARCHER"
    assert evidence.json()[0]["direction"] == "NEUTRAL"
    research_run = timeline.json()[-1]
    assert research_run["web_search_calls"] == 1
    assert research_run["tool_cost"] == "0.010000"
    assert research_run["web_sources"][0]["title"] == "Primary report"


async def test_researcher_requires_structured_project_and_unknowns_return_404(
    client: AsyncClient,
) -> None:
    project_id = await create_project(client)

    researcher = await client.post(f"/projects/{project_id}/researcher")
    hypotheses = await client.get(f"/projects/{uuid4()}/hypotheses")
    evidence = await client.get(f"/projects/{uuid4()}/evidence")

    assert researcher.status_code == 409
    assert hypotheses.status_code == 404
    assert evidence.status_code == 404
