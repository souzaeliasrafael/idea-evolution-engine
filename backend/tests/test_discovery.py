from datetime import UTC, datetime

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import DiscoveryCampaign
from app.domain.enums import DiscoveryCampaignStatus
from app.llm.dependencies import get_llm_router
from app.agents.discovery import IdeaGeneratorAgent
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app
from app.schemas.discovery import OpportunityGeneratorOutput
from app.schemas.discovery import DiscoveryHardConstraints
from app.services.discovery import _hard_constraint_violations


pytestmark = pytest.mark.anyio


class FailFirstGeneratorProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.generator_failures = 0

    async def generate(self, request):
        if request.role == "IDEA_GENERATOR" and self.generator_failures < 2:
            self.generator_failures += 1
            self.calls.append(request)
            raise RuntimeError("temporary generator failure")
        return await super().generate(request)


def test_generator_structured_output_requires_memory_lineage() -> None:
    schema = OpportunityGeneratorOutput.model_json_schema()
    generated = schema["$defs"]["GeneratedOpportunity"]
    assert "inspired_by_candidate_ids" in generated["required"]


def test_generator_accepts_a_smaller_high_quality_batch() -> None:
    output = OpportunityGeneratorOutput.model_validate({
        "opportunities": [{
            "title": f"Idea {index}",
            "problem": "A specific recurring consumer problem.",
            "target_customer": "Brazilian consumers",
            "solution": "A focused automated product.",
            "business_model": "Subscription",
            "acquisition_channel": "Consumer content",
            "pricing_hypothesis": "R$29 per month",
            "first_revenue_path": "Paid landing-page pilot",
            "founder_fit_reason": "Matches the available resources.",
            "signal_codes": ["S001"],
            "inspired_by_candidate_ids": [],
            "risks": ["Demand validation"],
            "business_case": {
                "customer_type": "B2C",
                "digital_product": True,
                "self_service": True,
                "automation_percent": 95,
                "mvp_days": 21,
                "recurring_human_service": False,
                "regulated_advice": False,
                "two_sided_marketplace": False,
                "revenue_pattern": "RECURRING",
            },
        } for index in range(3)]
    })
    IdeaGeneratorAgent(MockLLMProvider()).validate_output(output, {
        "campaign": {"candidate_target": 5},
        "signals": [{"code": "S001"}],
        "opportunity_memory": {"items": []},
    })


def test_generator_discards_unknown_memory_lineage_without_losing_the_idea() -> None:
    output = OpportunityGeneratorOutput.model_validate({
        "opportunities": [{
            "title": f"Idea {index}",
            "problem": "A recurring consumer problem with purchase evidence.",
            "target_customer": "Brazilian consumers",
            "solution": "A focused automated product.",
            "business_model": "Subscription",
            "acquisition_channel": "Consumer search",
            "pricing_hypothesis": "R$29 per month",
            "first_revenue_path": "Paid landing-page pilot",
            "founder_fit_reason": "Matches the available resources.",
            "signal_codes": ["S001"],
            "inspired_by_candidate_ids": ["f8f9ae0f-d26a-49c5-adeb-1cffffcac89e"],
            "risks": ["Demand validation"],
            "business_case": {
                "customer_type": "B2C",
                "digital_product": True,
                "self_service": True,
                "automation_percent": 95,
                "mvp_days": 21,
                "recurring_human_service": False,
                "regulated_advice": False,
                "two_sided_marketplace": False,
                "revenue_pattern": "RECURRING",
            },
        } for index in range(3)]
    })
    IdeaGeneratorAgent(MockLLMProvider()).validate_output(output, {
        "campaign": {"candidate_target": 5},
        "signals": [{"code": "S001"}],
        "opportunity_memory": {"items": []},
    })
    assert all(item.inspired_by_candidate_ids == [] for item in output.opportunities)


def test_hard_constraints_are_machine_enforced() -> None:
    violations = _hard_constraint_violations({
        "customer_type": "B2B",
        "digital_product": True,
        "self_service": False,
        "automation_percent": 40,
        "mvp_days": 90,
        "recurring_human_service": True,
        "regulated_advice": True,
        "two_sided_marketplace": True,
        "revenue_pattern": "ONE_OFF",
    }, DiscoveryHardConstraints())
    assert len(violations) == 8
    assert any("público B2B" in item for item in violations)
    assert any("operação humana" in item for item in violations)


async def test_discovery_campaign_ranks_and_promotes_a_business_opportunity(client: AsyncClient) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(provider)

    founder = await client.post("/founder-profiles", json={
        "name": "Founder Teste",
        "skills": ["software", "vendas consultivas"],
        "industries": ["serviços B2B"],
        "available_capital": "5000",
        "hours_per_week": 20,
        "target_monthly_revenue": "15000",
        "revenue_horizon_days": 90,
        "preferred_business_models": ["SaaS", "serviço produtizado"],
        "preferred_markets": ["PMEs brasileiras"],
        "distribution_assets": ["prospecção direta"],
        "technologies": ["Python", "TypeScript"],
        "exclusions": ["hardware"],
        "risk_tolerance": "MEDIUM",
    })
    assert founder.status_code == 201
    campaign = await client.post("/discovery-campaigns", json={
        "founder_profile_id": founder.json()["id"],
        "name": "Negócios digitais B2B",
        "brief": "Procurar dores vendáveis antes de construir.",
        "max_ai_budget": "1.00",
        "candidate_target": 5,
        "finalist_target": 2,
    })
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]

    run = await client.post(f"/discovery-campaigns/{campaign_id}/run")
    signals = await client.get(f"/discovery-campaigns/{campaign_id}/signals")
    candidates = await client.get(f"/discovery-campaigns/{campaign_id}/opportunities")
    runs = await client.get(f"/discovery-campaigns/{campaign_id}/runs")

    assert run.status_code == 200
    assert run.json()["status"] == "COMPLETED"
    assert len(signals.json()) == 5
    assert len(candidates.json()) == 5
    assert [item["rank"] for item in candidates.json()[:4]] == [1, 2, 3, 4]
    assert sum(item["status"] == "FINALIST" for item in candidates.json()) == 2
    assert all(item["market_gate_passed"] for item in candidates.json()[:4])
    assert all(item["market_reality_score"] >= 55 for item in candidates.json()[:4])
    assert len(runs.json()) == 4
    assert {item["agent"] for item in runs.json()} == {
        "OPPORTUNITY_SCOUT", "IDEA_GENERATOR", "OPPORTUNITY_RESEARCHER", "PORTFOLIO_JUDGE"
    }

    winner = candidates.json()[0]
    approved = await client.patch(f"/opportunities/{winner['id']}/feedback", json={
        "user_feedback": "APPROVED",
        "feedback_tags": [],
        "feedback_note": "Boa aderência ao meu acesso ao mercado.",
    })
    rejected = await client.patch(f"/opportunities/{candidates.json()[1]['id']}/feedback", json={
        "user_feedback": "REJECTED",
        "feedback_tags": ["Não combina comigo", "Venda difícil"],
        "feedback_note": "Depende de um canal que não possuo.",
    })
    assert approved.status_code == 200
    assert approved.json()["user_feedback"] == "APPROVED"
    assert rejected.json()["feedback_tags"] == ["Não combina comigo", "Venda difícil"]

    invalid_validation = await client.patch(f"/opportunities/{winner['id']}/commercial-validation", json={
        "status": "VALIDATED",
        "channel": "Landing page",
        "hypothesis": "Uma pessoa demonstrará intenção de compra.",
        "visits": 100,
        "leads": 12,
        "preorders": 1,
        "paying_customers": 0,
        "revenue": "0",
        "spend": "150",
        "currency": "BRL",
        "notes": "Sem pagamento confirmado.",
    })
    assert invalid_validation.status_code == 409

    validation = await client.patch(f"/opportunities/{winner['id']}/commercial-validation", json={
        "status": "VALIDATED",
        "channel": "Landing page com anúncios de busca",
        "hypothesis": "Ao menos 2% das visitas gerarão uma pré-venda.",
        "visits": 100,
        "leads": 12,
        "preorders": 2,
        "paying_customers": 1,
        "revenue": "447",
        "spend": "150",
        "currency": "BRL",
        "notes": "Teste controlado por sete dias.",
    })
    assert validation.status_code == 200
    assert validation.json()["validation_status"] == "VALIDATED"
    assert validation.json()["validation_result"]["score_delta"] > 0

    promoted = await client.post(f"/opportunities/{winner['id']}/promote", json={"max_ai_budget": "2.00"})
    assert promoted.status_code == 201
    assert promoted.json()["name"] == winner["title"]
    assert promoted.json()["agent_plan"] == {"builder": 1, "researcher": 1, "critic": 1}

    second = await client.post("/discovery-campaigns", json={
        "founder_profile_id": founder.json()["id"],
        "name": "Evoluir aprovadas",
        "brief": "Usar a memória para aprofundar somente padrões aprovados.",
        "max_ai_budget": "1.00",
        "candidate_target": 5,
        "finalist_target": 2,
        "memory_mode": "IMPROVE_APPROVED",
    })
    second_run = await client.post(f"/discovery-campaigns/{second.json()['id']}/run")
    second_candidates = await client.get(f"/discovery-campaigns/{second.json()['id']}/opportunities")
    second_generator_call = [call for call in provider.calls if call.role == "IDEA_GENERATOR"][-1]
    memory = second_generator_call.input_data["opportunity_memory"]
    assert second_run.json()["status"] == "COMPLETED"
    assert memory["mode"] == "IMPROVE_APPROVED"
    assert any(item["user_feedback"] == "APPROVED" for item in memory["items"])
    assert any("Venda difícil" in item["feedback_tags"] for item in memory["items"])
    assert len(second_candidates.json()) == 1


async def test_discovery_prompts_are_editable_and_versioned(client: AsyncClient) -> None:
    listed = await client.get("/discovery-prompts")
    assert listed.status_code == 200
    assert {item["agent"] for item in listed.json()} == {
        "OPPORTUNITY_SCOUT", "IDEA_GENERATOR", "OPPORTUNITY_RESEARCHER", "PORTFOLIO_JUDGE"
    }
    original = next(item for item in listed.json() if item["agent"] == "IDEA_GENERATOR")
    updated = await client.put("/discovery-prompts/IDEA_GENERATOR", json={
        "content": "Gere oportunidades específicas, rastreáveis e vendáveis. Retorne somente JSON válido conforme o schema."
    })
    versions = await client.get("/discovery-prompts/IDEA_GENERATOR/versions")
    reset = await client.delete("/discovery-prompts/IDEA_GENERATOR")
    assert updated.status_code == 200
    assert updated.json()["version"] == "custom-v1"
    assert len(versions.json()) == 1
    assert reset.json()["content"] == original["default_content"]


async def test_failed_campaign_resumes_from_persisted_scout_checkpoint(client: AsyncClient) -> None:
    provider = FailFirstGeneratorProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(provider)
    founder = await client.post("/founder-profiles", json={
        "name": "Resume test",
        "skills": ["software"],
        "hours_per_week": 10,
        "revenue_horizon_days": 90,
    })
    campaign = await client.post("/discovery-campaigns", json={
        "founder_profile_id": founder.json()["id"],
        "name": "Resume safely",
        "max_ai_budget": "1.00",
        "candidate_target": 3,
        "finalist_target": 1,
    })
    campaign_id = campaign.json()["id"]
    failed = await client.post(f"/discovery-campaigns/{campaign_id}/run")
    resumed = await client.post(f"/discovery-campaigns/{campaign_id}/run")
    assert failed.json()["status"] == "FAILED"
    assert resumed.json()["status"] == "COMPLETED"
    assert len([call for call in provider.calls if call.role == "OPPORTUNITY_SCOUT"]) == 1


async def test_orphaned_discovery_campaign_is_released_and_can_resume(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    founder = await client.post(
        "/founder-profiles",
        json={"name": "Recovery", "skills": ["software"]},
    )
    created = await client.post(
        "/discovery-campaigns",
        json={
            "founder_profile_id": founder.json()["id"],
            "name": "Recover orphan",
            "max_ai_budget": "1.00",
            "candidate_target": 3,
            "finalist_target": 1,
        },
    )
    campaign_id = created.json()["id"]
    async with session_maker() as session:
        campaign = await session.get(DiscoveryCampaign, campaign_id)
        assert campaign is not None
        campaign.status = DiscoveryCampaignStatus.RUNNING
        campaign.current_stage = "VALIDANDO_MERCADO"
        campaign.started_at = datetime.now(UTC)
        await session.commit()

    recovered = await client.get(f"/discovery-campaigns/{campaign_id}")
    resumed = await client.post(f"/discovery-campaigns/{campaign_id}/run")

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "FAILED"
    assert recovered.json()["current_stage"] == "INTERROMPIDA"
    assert "checkpoints" in recovered.json()["error"]
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "COMPLETED"


async def test_cancelling_an_orphaned_discovery_campaign_finishes_immediately(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    founder = await client.post(
        "/founder-profiles",
        json={"name": "Cancel recovery", "skills": ["software"]},
    )
    created = await client.post(
        "/discovery-campaigns",
        json={
            "founder_profile_id": founder.json()["id"],
            "name": "Cancel orphan",
            "max_ai_budget": "1.00",
            "candidate_target": 3,
            "finalist_target": 1,
        },
    )
    campaign_id = created.json()["id"]
    async with session_maker() as session:
        campaign = await session.get(DiscoveryCampaign, campaign_id)
        assert campaign is not None
        campaign.status = DiscoveryCampaignStatus.RUNNING
        campaign.current_stage = "VALIDANDO_MERCADO"
        campaign.started_at = datetime.now(UTC)
        await session.commit()

    cancelled = await client.post(f"/discovery-campaigns/{campaign_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["current_stage"] == "CANCELADA"
    assert cancelled.json()["completed_at"] is not None
