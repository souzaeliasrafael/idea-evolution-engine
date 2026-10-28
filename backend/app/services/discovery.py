import asyncio
import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError, AgentResult, LLMAttempt
from app.agents.discovery import (
    IdeaGeneratorAgent,
    OpportunityResearcherAgent,
    OpportunityScoutAgent,
    PortfolioJudgeAgent,
)
from app.database.models import (
    AgentProfile,
    DiscoveryHandoff,
    DiscoveryAgentRun,
    DiscoveryCampaign,
    Evidence,
    FounderProfile,
    Hypothesis,
    IdeaVersion,
    OpportunityCandidate,
    OpportunitySignal,
)
from app.domain.enums import (
    AgentType,
    CommercialValidationStatus,
    DiscoveryAgentType,
    DiscoveryCampaignStatus,
    DiscoveryMemoryMode,
    EpistemicClassification,
    EvidenceDirection,
    EvidenceOrigin,
    HypothesisOrigin,
    HypothesisStatus,
    OpportunityFeedbackStatus,
    OpportunityCustomerType,
    OpportunityRevenuePattern,
    OpportunityStatus,
)
from app.llm.base import LLMProvider
from app.llm.router import LLMRouter
from app.schemas.discovery import (
    CommercialValidationUpdate,
    DiscoveryCampaignCreate,
    DiscoveryHardConstraints,
    FounderProfileCreate,
    FounderProfileUpdate,
    OpportunityGeneratorOutput,
    OpportunityFeedbackUpdate,
    OpportunityPromoteRequest,
)
from app.schemas.project import ProjectCreate
from app.schemas.idea import IdeaConcept
from app.services import profiles as profile_service
from app.services import projects as project_service
from app.services import discovery_prompts as discovery_prompt_service
from app.services.knowledge import register_concept_hypotheses


class DiscoveryNotFoundError(LookupError):
    pass


class DiscoveryStateError(RuntimeError):
    pass


class DiscoveryBudgetError(RuntimeError):
    pass


_active_tasks: dict[str, asyncio.Task[object]] = {}


def _recover_orphaned_campaign(campaign: DiscoveryCampaign) -> bool:
    """Release a RUNNING row whose request no longer exists in this worker."""

    if campaign.status != DiscoveryCampaignStatus.RUNNING:
        return False
    task = _active_tasks.get(campaign.id)
    if task is not None and not task.done():
        return False

    cancelled = campaign.cancellation_requested
    campaign.status = (
        DiscoveryCampaignStatus.CANCELLED
        if cancelled
        else DiscoveryCampaignStatus.FAILED
    )
    campaign.current_stage = "CANCELADA" if cancelled else "INTERROMPIDA"
    campaign.cancellation_requested = False
    campaign.completed_at = datetime.now(UTC)
    if not cancelled:
        campaign.error = (
            "A execução foi interrompida por reinício ou encerramento do servidor. "
            "Execute novamente para retomar dos checkpoints já salvos."
        )
    return True


async def create_founder_profile(session: AsyncSession, payload: FounderProfileCreate) -> FounderProfile:
    profile = FounderProfile(**payload.model_dump(mode="python"))
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def list_founder_profiles(session: AsyncSession) -> Sequence[FounderProfile]:
    return (await session.scalars(select(FounderProfile).order_by(FounderProfile.updated_at.desc()))).all()


async def update_founder_profile(
    session: AsyncSession, profile_id: UUID, payload: FounderProfileUpdate
) -> FounderProfile:
    profile = await session.get(FounderProfile, str(profile_id))
    if profile is None:
        raise DiscoveryNotFoundError("Founder profile not found")
    for key, value in payload.model_dump(mode="python").items():
        setattr(profile, key, value)
    await session.commit()
    await session.refresh(profile)
    return profile


async def create_campaign(session: AsyncSession, payload: DiscoveryCampaignCreate) -> DiscoveryCampaign:
    if await session.get(FounderProfile, str(payload.founder_profile_id)) is None:
        raise DiscoveryNotFoundError("Founder profile not found")
    if payload.agent_profile_id and await session.get(AgentProfile, str(payload.agent_profile_id)) is None:
        raise DiscoveryNotFoundError("Agent profile not found")
    campaign_data = payload.model_dump(
        mode="python",
        exclude={"founder_profile_id", "agent_profile_id", "hard_constraints"},
    )
    campaign = DiscoveryCampaign(
        **campaign_data,
        founder_profile_id=str(payload.founder_profile_id),
        agent_profile_id=str(payload.agent_profile_id) if payload.agent_profile_id else None,
        hard_constraints=payload.hard_constraints.model_dump(mode="json"),
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


async def list_campaigns(session: AsyncSession) -> Sequence[DiscoveryCampaign]:
    campaigns = list(
        (
            await session.scalars(
                select(DiscoveryCampaign).order_by(
                    DiscoveryCampaign.created_at.desc()
                )
            )
        ).all()
    )
    recovered = False
    for campaign in campaigns:
        recovered = _recover_orphaned_campaign(campaign) or recovered
    if recovered:
        await session.commit()
    return campaigns


async def get_campaign(session: AsyncSession, campaign_id: UUID) -> DiscoveryCampaign:
    campaign = await session.get(DiscoveryCampaign, str(campaign_id))
    if campaign is None:
        raise DiscoveryNotFoundError("Discovery campaign not found")
    if _recover_orphaned_campaign(campaign):
        await session.commit()
    return campaign


async def list_signals(session: AsyncSession, campaign_id: UUID) -> Sequence[OpportunitySignal]:
    await get_campaign(session, campaign_id)
    return (await session.scalars(
        select(OpportunitySignal).where(OpportunitySignal.campaign_id == str(campaign_id)).order_by(OpportunitySignal.sequence)
    )).all()


async def list_candidates(session: AsyncSession, campaign_id: UUID) -> Sequence[OpportunityCandidate]:
    await get_campaign(session, campaign_id)
    return (await session.scalars(
        select(OpportunityCandidate)
        .where(OpportunityCandidate.campaign_id == str(campaign_id))
        .order_by(OpportunityCandidate.rank.is_(None), OpportunityCandidate.rank, OpportunityCandidate.preliminary_score.desc())
    )).all()


async def list_runs(session: AsyncSession, campaign_id: UUID) -> Sequence[DiscoveryAgentRun]:
    await get_campaign(session, campaign_id)
    return (await session.scalars(
        select(DiscoveryAgentRun).where(DiscoveryAgentRun.campaign_id == str(campaign_id)).order_by(DiscoveryAgentRun.created_at)
    )).all()


async def update_candidate_feedback(
    session: AsyncSession,
    candidate_id: UUID,
    payload: OpportunityFeedbackUpdate,
) -> OpportunityCandidate:
    candidate = await session.get(OpportunityCandidate, str(candidate_id))
    if candidate is None:
        raise DiscoveryNotFoundError("Opportunity not found")
    candidate.user_feedback = payload.user_feedback
    candidate.feedback_tags = list(dict.fromkeys(payload.feedback_tags))
    candidate.feedback_note = payload.feedback_note
    candidate.feedback_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def update_commercial_validation(
    session: AsyncSession,
    candidate_id: UUID,
    payload: CommercialValidationUpdate,
) -> OpportunityCandidate:
    candidate = await session.get(OpportunityCandidate, str(candidate_id))
    if candidate is None:
        raise DiscoveryNotFoundError("Opportunity not found")
    campaign = await session.get(DiscoveryCampaign, candidate.campaign_id)
    if campaign is None:
        raise DiscoveryNotFoundError("Discovery campaign not found")
    if payload.leads > payload.visits and payload.visits > 0:
        raise DiscoveryStateError("Leads não podem superar visitas")
    if payload.preorders > payload.leads and payload.leads > 0:
        raise DiscoveryStateError("Pré-vendas não podem superar leads")
    if payload.status == CommercialValidationStatus.VALIDATED and (
        payload.preorders + payload.paying_customers == 0 or payload.revenue <= 0
    ):
        raise DiscoveryStateError(
            "Para marcar como validada, registre receita e ao menos uma pré-venda ou cliente pagante"
        )

    previous = candidate.validation_result if isinstance(candidate.validation_result, dict) else {}
    baseline_score = float(
        previous.get("baseline_overall_score", candidate.overall_score or candidate.preliminary_score or 0)
    )
    research = candidate.research if isinstance(candidate.research, dict) else {}
    baseline_confidence = float(
        previous.get("baseline_confidence", candidate.confidence or research.get("confidence", 0))
    )
    baseline_market_score = float(
        previous.get("baseline_market_reality_score", candidate.market_reality_score or 0)
    )
    purchase_count = payload.preorders + payload.paying_customers
    purchase_rate = purchase_count / payload.visits if payload.visits else 0
    lead_rate = payload.leads / payload.visits if payload.visits else 0
    revenue_multiple = float(payload.revenue / payload.spend) if payload.spend else None

    score_delta = 0.0
    confidence_delta = 0.0
    market_delta = 0.0
    if payload.status == CommercialValidationStatus.VALIDATED:
        score_delta = min(12.0, 4.0 + purchase_count * 1.5 + min(purchase_rate * 100, 4.0))
        confidence_delta = min(0.25, 0.10 + purchase_count * 0.025)
        market_delta = min(20.0, 8.0 + purchase_count * 2.0)
        candidate.market_gate_passed = candidate.hard_constraint_passed
        candidate.disqualification_reasons = [
            reason for reason in candidate.disqualification_reasons
            if not reason.startswith("Mercado:")
        ]
        if candidate.hard_constraint_passed and candidate.status == OpportunityStatus.REJECTED:
            candidate.status = OpportunityStatus.SHORTLISTED
    elif payload.status == CommercialValidationStatus.INVALIDATED:
        score_delta = -12.0
        confidence_delta = -0.15
        market_delta = -20.0
        candidate.market_gate_passed = False
        reason = "Mercado: o experimento comercial invalidou a hipótese de compra."
        if reason not in candidate.disqualification_reasons:
            candidate.disqualification_reasons = [*candidate.disqualification_reasons, reason]

    candidate.overall_score = round(max(0.0, min(100.0, baseline_score + score_delta)), 2)
    candidate.confidence = round(max(0.0, min(1.0, baseline_confidence + confidence_delta)), 4)
    adjusted_market_score = max(0.0, min(100.0, baseline_market_score + market_delta))
    if payload.status == CommercialValidationStatus.VALIDATED and candidate.hard_constraint_passed:
        adjusted_market_score = max(
            adjusted_market_score,
            float(_constraints(campaign).min_market_reality_score),
        )
    candidate.market_reality_score = round(adjusted_market_score, 2)
    candidate.validation_status = payload.status
    candidate.validation_result = {
        **payload.model_dump(mode="json"),
        "lead_rate": round(lead_rate, 4),
        "purchase_rate": round(purchase_rate, 4),
        "revenue_multiple": round(revenue_multiple, 2) if revenue_multiple is not None else None,
        "baseline_overall_score": baseline_score,
        "baseline_confidence": baseline_confidence,
        "baseline_market_reality_score": baseline_market_score,
        "score_delta": round(score_delta, 2),
        "confidence_delta": round(confidence_delta, 4),
        "market_reality_delta": round(market_delta, 2),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def cancel_campaign(session: AsyncSession, campaign_id: UUID) -> DiscoveryCampaign:
    campaign = await session.get(DiscoveryCampaign, str(campaign_id))
    if campaign is None:
        raise DiscoveryNotFoundError("Discovery campaign not found")
    if campaign.status != DiscoveryCampaignStatus.RUNNING:
        return campaign
    task = _active_tasks.get(campaign.id)
    if task is None or task.done():
        campaign.status = DiscoveryCampaignStatus.CANCELLED
        campaign.cancellation_requested = False
        campaign.current_stage = "CANCELADA"
        campaign.completed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(campaign)
        return campaign
    campaign.cancellation_requested = True
    campaign.current_stage = "CANCELAMENTO_SOLICITADO"
    await session.commit()
    if task is not asyncio.current_task():
        task.cancel()
    await session.refresh(campaign)
    return campaign


async def run_campaign(
    session: AsyncSession, campaign_id: UUID, fallback_router: LLMRouter
) -> DiscoveryCampaign:
    campaign = await get_campaign(session, campaign_id)
    if campaign.status not in {
        DiscoveryCampaignStatus.DRAFT,
        DiscoveryCampaignStatus.FAILED,
        DiscoveryCampaignStatus.CANCELLED,
        DiscoveryCampaignStatus.BUDGET_STOPPED,
    }:
        raise DiscoveryStateError("Campaign is already running or completed")

    is_resume = campaign.status != DiscoveryCampaignStatus.DRAFT
    # A first run starts clean. A retry preserves completed checkpoints and the
    # real cumulative cost, so a transient failure never pays for valid work twice.
    if not is_resume:
        await session.execute(delete(OpportunityCandidate).where(OpportunityCandidate.campaign_id == campaign.id))
        await session.execute(delete(OpportunitySignal).where(OpportunitySignal.campaign_id == campaign.id))
        campaign.total_cost = Decimal("0")
    current_task = asyncio.current_task()
    if current_task is not None:
        _active_tasks[campaign.id] = current_task

    campaign.status = DiscoveryCampaignStatus.RUNNING
    campaign.cancellation_requested = False
    campaign.error = None
    campaign.started_at = datetime.now(UTC)
    campaign.completed_at = None
    await session.commit()

    try:
        router = await profile_service.router_for_profile(session, campaign.agent_profile_id, fallback_router)
        founder = await session.get(FounderProfile, campaign.founder_profile_id)
        if founder is None:
            raise DiscoveryNotFoundError("Founder profile not found")
        founder_data = _founder_data(founder)
        campaign_data = _campaign_data(campaign)
        opportunity_memory = await _opportunity_memory(session, campaign)

        signals = list(await list_signals(session, campaign_id))
        if not signals:
            campaign.current_stage = "PESQUISANDO_SINAIS"
            await session.commit()
            scout_prompt = await discovery_prompt_service.get_effective_prompt(session, DiscoveryAgentType.OPPORTUNITY_SCOUT)
            scout = OpportunityScoutAgent(router.provider_for(AgentType.RESEARCHER), prompt=scout_prompt.content, prompt_version=scout_prompt.version)
            scout_result = await _execute_and_record(
                session, campaign, DiscoveryAgentType.OPPORTUNITY_SCOUT, scout.provider, scout.prompt_version,
                lambda: scout.run(founder=founder_data, campaign=campaign_data),
            )
            for sequence, signal in enumerate(scout_result.output.signals, 1):
                session.add(OpportunitySignal(campaign_id=campaign.id, sequence=sequence, **signal.model_dump()))
            await session.commit()
            signals = list(await list_signals(session, campaign_id))
        else:
            campaign.current_stage = "REUTILIZANDO_SINAIS"
            await session.commit()
        signal_data = [_signal_data(item) for item in signals]

        all_candidates = list(await list_candidates(session, campaign_id))
        if not all_candidates:
            await _checkpoint(session, campaign)
            generated_items = await _recover_generator_opportunities(
                session,
                campaign,
                known_signal_codes={item.code for item in signals},
                known_memory_ids={item["candidate_id"] for item in opportunity_memory["items"]},
            )
            if generated_items:
                campaign.current_stage = "RECUPERANDO_GERACAO"
                await session.commit()
            else:
                campaign.current_stage = "GERANDO_OPORTUNIDADES"
                await session.commit()
                generator_prompt = await discovery_prompt_service.get_effective_prompt(session, DiscoveryAgentType.IDEA_GENERATOR)
                generator = IdeaGeneratorAgent(router.provider_for(AgentType.STRUCTURER), prompt=generator_prompt.content, prompt_version=generator_prompt.version)
                generation = await _execute_and_record(
                    session, campaign, DiscoveryAgentType.IDEA_GENERATOR, generator.provider, generator.prompt_version,
                    lambda: generator.run(
                        founder=founder_data,
                        campaign=campaign_data,
                        signals=signal_data,
                        opportunity_memory=opportunity_memory,
                    ),
                )
                generated_items = list(generation.output.opportunities)
            unique = _deduplicate(
                generated_items[:min(campaign.candidate_target, 5)],
                opportunity_memory["items"],
                campaign.memory_mode,
            )
            if not unique:
                raise DiscoveryStateError(
                    "Todas as oportunidades geradas repetiram padrões da memória. "
                    "Crie outra campanha com um foco diferente ou use outro modo de memória."
                )
            signal_map = {item.code: item for item in signals}
            constraints = _constraints(campaign)
            for item in unique:
                business_case = item.business_case.model_dump(mode="json")
                violations = _hard_constraint_violations(business_case, constraints)
                session.add(OpportunityCandidate(
                    campaign_id=campaign.id,
                    preliminary_score=_preliminary_score(item.signal_codes, signal_map),
                    business_case=business_case,
                    hard_constraint_passed=not violations,
                    disqualification_reasons=violations,
                    **item.model_dump(exclude={"business_case"}),
                ))
            await session.flush()
            all_candidates = list(await list_candidates(session, campaign_id))
            eligible_candidates = [item for item in all_candidates if item.hard_constraint_passed]
            shortlist_size = min(
                len(eligible_candidates),
                max(min(campaign.finalist_target, 3) * 2, min(campaign.finalist_target, 3)),
            )
            shortlisted = eligible_candidates[:shortlist_size]
            for item in shortlisted:
                item.status = OpportunityStatus.SHORTLISTED
            for item in all_candidates:
                if item not in shortlisted:
                    if item.hard_constraint_passed and not item.disqualification_reasons:
                        item.disqualification_reasons = [
                            "Pré-seleção: ficou abaixo do corte para pesquisa aprofundada."
                        ]
                    item.status = OpportunityStatus.REJECTED
            await session.commit()
        else:
            campaign.current_stage = "REUTILIZANDO_OPORTUNIDADES"
            shortlisted = [
                item for item in all_candidates
                if item.status in {OpportunityStatus.SHORTLISTED, OpportunityStatus.FINALIST}
            ]
            if not shortlisted:
                eligible_candidates = [item for item in all_candidates if item.hard_constraint_passed]
                shortlist_size = min(
                    len(eligible_candidates),
                    max(min(campaign.finalist_target, 3) * 2, min(campaign.finalist_target, 3)),
                )
                shortlisted = eligible_candidates[:shortlist_size]
            await session.commit()

        if shortlisted and not all(_has_market_research(candidate.research) for candidate in shortlisted):
            await _checkpoint(session, campaign)
            campaign.current_stage = "VALIDANDO_MERCADO"
            await session.commit()
            researcher_prompt = await discovery_prompt_service.get_effective_prompt(session, DiscoveryAgentType.OPPORTUNITY_RESEARCHER)
            researcher = OpportunityResearcherAgent(router.provider_for(AgentType.RESEARCHER), prompt=researcher_prompt.content, prompt_version=researcher_prompt.version)
            research = await _execute_and_record(
                session, campaign, DiscoveryAgentType.OPPORTUNITY_RESEARCHER, researcher.provider, researcher.prompt_version,
                lambda: researcher.run(
                    founder=founder_data,
                    campaign=campaign_data,
                    signals=signal_data,
                    candidates=[_candidate_data(item) for item in shortlisted],
                ),
            )
            analysis_by_id = {item.candidate_id: item for item in research.output.analyses}
            constraints = _constraints(campaign)
            for candidate in shortlisted:
                analysis = analysis_by_id[candidate.id]
                candidate.research = analysis.model_dump(mode="json")
                candidate.market_reality_score = _market_reality_score(analysis)
                market_failures = _market_gate_failures(analysis, candidate.market_reality_score, constraints)
                candidate.market_gate_passed = not market_failures
                candidate.disqualification_reasons = [
                    reason for reason in candidate.disqualification_reasons
                    if not reason.startswith("Mercado:")
                ] + market_failures
                if market_failures:
                    candidate.status = OpportunityStatus.REJECTED
            await session.commit()
        else:
            campaign.current_stage = "REUTILIZANDO_PESQUISA"
            await session.commit()

        judge_candidates = [item for item in shortlisted if item.market_gate_passed]
        if judge_candidates:
            await _checkpoint(session, campaign)
            campaign.current_stage = "COMPARANDO_PORTFOLIO"
            await session.commit()
            judge_prompt = await discovery_prompt_service.get_effective_prompt(session, DiscoveryAgentType.PORTFOLIO_JUDGE)
            judge = PortfolioJudgeAgent(router.provider_for(AgentType.JUDGE), prompt=judge_prompt.content, prompt_version=judge_prompt.version)
            judgment = await _execute_and_record(
                session, campaign, DiscoveryAgentType.PORTFOLIO_JUDGE, judge.provider, judge.prompt_version,
                lambda: judge.run(
                    founder=founder_data,
                    campaign=campaign_data,
                    candidates=[_candidate_data(item, include_research=True) for item in judge_candidates],
                    opportunity_memory=opportunity_memory,
                ),
            )
            evaluation_by_id = {item.candidate_id: item for item in judgment.output.evaluations}
            for candidate in judge_candidates:
                evaluation = evaluation_by_id[candidate.id]
                candidate.scores = _score_dict(evaluation)
                adjustment, matched_rejection_tags = _feedback_adjustment(
                    candidate, evaluation, opportunity_memory
                )
                candidate.overall_score = _weighted_score(
                    candidate.scores,
                    candidate.market_reality_score or 0,
                    adjustment,
                )
                research_confidence = float(candidate.research.get("confidence", 0))
                candidate.confidence = min(evaluation.confidence, research_confidence)
                if not bool(candidate.research.get("direct_purchase_evidence")):
                    candidate.confidence = min(candidate.confidence, 0.35)
                candidate.research = {
                    **candidate.research,
                    "judge_rationale": evaluation.rationale,
                    "matched_rejection_tags": matched_rejection_tags,
                    "preference_adjustment": adjustment,
                    "validation_plan": evaluation.validation_plan,
                }
        else:
            campaign.current_stage = "SEM_FINALISTAS_COMPROVADAS"
            await session.commit()

        ranked = sorted(
            judge_candidates,
            key=lambda item: (item.overall_score or 0, item.confidence or 0),
            reverse=True,
        )
        for rank, candidate in enumerate(ranked, 1):
            candidate.rank = rank
            candidate.status = (
                OpportunityStatus.FINALIST
                if rank <= min(campaign.finalist_target, 3)
                else OpportunityStatus.SHORTLISTED
            )
        campaign.status = DiscoveryCampaignStatus.COMPLETED
        campaign.current_stage = "CONCLUIDA"
        campaign.completed_at = datetime.now(UTC)
        await session.commit()
    except asyncio.CancelledError:
        await session.rollback()
        campaign = await get_campaign(session, campaign_id)
        campaign.status = DiscoveryCampaignStatus.CANCELLED
        campaign.current_stage = "CANCELADA"
        campaign.completed_at = datetime.now(UTC)
        await session.commit()
    except DiscoveryBudgetError as exc:
        await session.rollback()
        campaign = await get_campaign(session, campaign_id)
        campaign.status = DiscoveryCampaignStatus.BUDGET_STOPPED
        campaign.current_stage = "ORCAMENTO_ENCERRADO"
        campaign.error = str(exc)
        campaign.completed_at = datetime.now(UTC)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        campaign = await get_campaign(session, campaign_id)
        campaign.status = DiscoveryCampaignStatus.FAILED
        campaign.current_stage = "FALHA"
        campaign.error = f"{type(exc).__name__}: {exc}"[:2000]
        campaign.completed_at = datetime.now(UTC)
        await session.commit()
    finally:
        _active_tasks.pop(str(campaign_id), None)
    return await get_campaign(session, campaign_id)


async def promote_candidate(
    session: AsyncSession,
    candidate_id: UUID,
    payload: OpportunityPromoteRequest,
):
    candidate = await session.get(OpportunityCandidate, str(candidate_id))
    if candidate is None:
        raise DiscoveryNotFoundError("Opportunity not found")
    if candidate.project_id is not None:
        raise DiscoveryStateError("Opportunity has already been promoted")
    campaign = await session.get(DiscoveryCampaign, candidate.campaign_id)
    if campaign is None:
        raise DiscoveryNotFoundError("Discovery campaign not found")
    if not payload.allow_manual_override and (
        campaign.status != DiscoveryCampaignStatus.COMPLETED
        or candidate.status != OpportunityStatus.FINALIST
    ):
        raise DiscoveryStateError(
            "A promoção normal exige campanha concluída e oportunidade finalista; "
            "use a substituição manual explicitamente para assumir esse risco"
        )
    if not candidate.hard_constraint_passed:
        raise DiscoveryStateError("A oportunidade violou regras eliminatórias da campanha")
    if not candidate.market_gate_passed and candidate.validation_status != CommercialValidationStatus.VALIDATED:
        raise DiscoveryStateError(
            "A oportunidade ainda não passou pelo filtro de mercado nem por validação comercial"
        )
    raw_idea = (
        f"Problema: {candidate.problem}\n\nCliente-alvo: {candidate.target_customer}\n\n"
        f"Solução proposta: {candidate.solution}\n\nModelo de negócio: {candidate.business_model}\n\n"
        f"Aquisição inicial: {candidate.acquisition_channel}\n\nPreço: {candidate.pricing_hypothesis}\n\n"
        f"Primeira receita: {candidate.first_revenue_path}\n\nAderência ao fundador: {candidate.founder_fit_reason}\n\n"
        f"Riscos: {'; '.join(candidate.risks)}"
    )
    project = await project_service.create_project(
        session,
        ProjectCreate(
            name=candidate.title,
            raw_idea=raw_idea,
            max_ai_budget=payload.max_ai_budget,
            agent_profile_id=UUID(campaign.agent_profile_id) if campaign.agent_profile_id else None,
        ),
    )
    candidate = await session.get(OpportunityCandidate, str(candidate_id))
    candidate.project_id = project.id
    candidate.status = OpportunityStatus.SELECTED
    signals = list(
        (
            await session.scalars(
                select(OpportunitySignal)
                .where(OpportunitySignal.campaign_id == campaign.id)
                .order_by(OpportunitySignal.sequence.asc())
            )
        ).all()
    )
    linked_signals = [item for item in signals if item.code in candidate.signal_codes]
    snapshot = _handoff_snapshot(campaign, candidate, linked_signals)
    session.add(
        DiscoveryHandoff(
            project_id=project.id,
            campaign_id=campaign.id,
            candidate_id=candidate.id,
            schema_version=1,
            snapshot=snapshot,
        )
    )
    concept, hypothesis_targets = _concept_from_handoff(candidate, raw_idea)
    version = IdeaVersion(
        project_id=project.id,
        version=0,
        parent_version_id=None,
        reason_for_change="Structured import from completed discovery campaign",
        created_by=AgentType.STRUCTURER,
        changes=[
            "Imported the selected discovery finalist without another paid structuring call",
            "Transferred discovery assumptions and source evidence",
        ],
        concept=concept.model_dump(mode="json"),
    )
    session.add(version)
    await session.flush()
    await register_concept_hypotheses(
        session,
        project_id=project.id,
        source_version_id=version.id,
        concept=concept.model_dump(mode="json"),
        origin=HypothesisOrigin.STRUCTURER,
    )
    await session.flush()
    await _import_discovery_evidence(
        session,
        project.id,
        candidate,
        linked_signals,
        hypothesis_targets,
    )
    await session.commit()
    await session.refresh(project)
    return project


async def get_project_handoff(
    session: AsyncSession, project_id: UUID
) -> DiscoveryHandoff | None:
    return await session.scalar(
        select(DiscoveryHandoff).where(DiscoveryHandoff.project_id == str(project_id))
    )


def _concept_from_handoff(
    candidate: OpportunityCandidate, raw_idea: str
) -> tuple[IdeaConcept, dict[str, str]]:
    business_case = candidate.business_case or {}
    demand = (
        f"O público {candidate.target_customer} tem o problema descrito e aceita pagar "
        f"nos termos de {candidate.pricing_hypothesis}."
    )
    channel = (
        f"O canal {candidate.acquisition_channel} alcança clientes com CAC compatível "
        "com a margem proposta."
    )
    differentiation = (
        "A proposta oferece diferenciação relevante frente às alternativas pagas "
        "encontradas na descoberta."
    )
    feasibility = (
        f"O MVP pode ser entregue em até {business_case.get('mvp_days', '30')} dias "
        f"com ao menos {business_case.get('automation_percent', '90')}% de automação."
    )
    research = candidate.research if isinstance(candidate.research, dict) else {}
    unknowns = [*candidate.risks]
    recommended = str(research.get("recommended_validation", "")).strip()
    if recommended:
        unknowns.append(recommended)
    concept = IdeaConcept(
        title=candidate.title,
        raw_idea=raw_idea,
        problem=candidate.problem,
        solution=candidate.solution,
        target_users=[candidate.target_customer],
        value_proposition=(
            f"Resolver {candidate.problem} por meio de {candidate.solution}"
        ),
        possible_use_cases=[candidate.first_revenue_path],
        business_models=[candidate.business_model, candidate.pricing_hypothesis],
        technical_assumptions=[feasibility],
        business_assumptions=[demand, channel, differentiation],
        unknowns=unknowns[:8] or ["Validar demanda e disposição de pagar."],
        risks=candidate.risks[:8] or ["A evidência de mercado ainda pode ser insuficiente."],
        initial_mvp=(
            f"Entregar uma versão self-service focada em {candidate.target_customer}; "
            f"captar os primeiros clientes por {candidate.acquisition_channel} e validar "
            f"a receita por {candidate.first_revenue_path}."
        ),
    )
    return concept, {
        "demand": demand,
        "channel": channel,
        "differentiation": differentiation,
        "feasibility": feasibility,
    }


def _handoff_snapshot(
    campaign: DiscoveryCampaign,
    candidate: OpportunityCandidate,
    signals: list[OpportunitySignal],
) -> dict[str, object]:
    return {
        "schema": "discovery_handoff_v1",
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "geography": campaign.geography,
            "status": campaign.status.value,
            "cost": str(campaign.total_cost),
        },
        "candidate": _candidate_data(candidate, include_research=True),
        "signals": [_signal_data(item) for item in signals],
        "score_provenance": {
            "stage": "DISCOVERY",
            "preliminary": candidate.preliminary_score,
            "market_reality": candidate.market_reality_score,
            "overall": candidate.overall_score,
            "confidence": candidate.confidence,
            "rank": candidate.rank,
        },
    }


async def _import_discovery_evidence(
    session: AsyncSession,
    project_id: str,
    candidate: OpportunityCandidate,
    signals: list[OpportunitySignal],
    targets: dict[str, str],
) -> None:
    hypothesis_rows = list(
        (
            await session.scalars(
                select(Hypothesis).where(Hypothesis.project_id == project_id)
            )
        ).all()
    )
    by_statement = {item.statement: item for item in hypothesis_rows}
    records: list[tuple[str, str, str, str, int]] = []
    for signal in signals:
        records.append((
            "demand",
            signal.source_title,
            signal.source_url,
            f"{signal.observed_signal} Sinal comercial: {signal.commercial_signal}",
            max(1, min(5, signal.commercial_strength)),
        ))
    research = candidate.research if isinstance(candidate.research, dict) else {}
    for key, target in (("demand_evidence", "demand"), ("competitor_evidence", "differentiation")):
        for item in research.get(key, []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("source_url", ""))
            host = urlsplit(url).netloc.removeprefix("www.")
            records.append((
                target,
                host or "Pesquisa de descoberta",
                url,
                str(item.get("claim", "Evidência importada da descoberta")),
                4 if item.get("supports_purchase_behavior") else 2,
            ))
    next_sequence = int(
        await session.scalar(
            select(func.max(Evidence.sequence)).where(Evidence.project_id == project_id)
        )
        or 0
    ) + 1
    seen: set[tuple[str, str]] = set()
    for target, source, url, claim, strength in records:
        hypothesis = by_statement.get(targets[target])
        marker = (hypothesis.id if hypothesis else "", url.casefold())
        if hypothesis is None or not url or marker in seen:
            continue
        seen.add(marker)
        session.add(Evidence(
            project_id=project_id,
            sequence=next_sequence,
            hypothesis_id=hypothesis.id,
            agent_run_id=None,
            origin=EvidenceOrigin.RESEARCHER,
            source=source,
            source_type="DISCOVERY_IMPORT",
            claim=claim,
            direction=EvidenceDirection.SUPPORT,
            strength=strength,
            epistemic_classification=EpistemicClassification.FACT,
            url=url,
            date=None,
        ))
        hypothesis.status = HypothesisStatus.PARTIAL
        hypothesis.confidence = max(hypothesis.confidence, min(0.75, strength / 5))
        next_sequence += 1


async def _execute_and_record(
    session: AsyncSession,
    campaign: DiscoveryCampaign,
    agent: DiscoveryAgentType,
    provider: LLMProvider,
    prompt_version: str,
    operation,
) -> AgentResult:
    await _checkpoint(session, campaign)
    try:
        result = await operation()
    except AgentExecutionError as exc:
        await _add_runs(session, campaign, agent, provider, prompt_version, exc.input_data, exc.attempts)
        await session.commit()
        detail = next(
            (attempt.error for attempt in reversed(exc.attempts) if attempt.error),
            "typed output validation failed",
        )
        raise DiscoveryStateError(f"{agent.value} falhou: {detail}") from exc
    await _add_runs(session, campaign, agent, provider, result.prompt_version, result.input_data, result.attempts)
    await session.commit()
    await _checkpoint(session, campaign)
    return result


async def _add_runs(
    session: AsyncSession,
    campaign: DiscoveryCampaign,
    agent: DiscoveryAgentType,
    provider: LLMProvider,
    prompt_version: str,
    input_data: dict,
    attempts: tuple[LLMAttempt, ...],
) -> None:
    cost = Decimal("0")
    for attempt in attempts:
        response = attempt.response
        if response is not None:
            cost += response.estimated_cost
        session.add(DiscoveryAgentRun(
            campaign_id=campaign.id,
            agent=agent,
            provider=provider.provider_name,
            model=response.model if response else provider.model_name,
            prompt_version=prompt_version,
            input_json=input_data,
            output_json=attempt.output_json,
            input_tokens=response.input_tokens if response else 0,
            output_tokens=response.output_tokens if response else 0,
            cached_input_tokens=response.cached_input_tokens if response else 0,
            reasoning_tokens=response.reasoning_tokens if response else 0,
            web_search_calls=response.web_search_calls if response else 0,
            tool_cost=response.tool_cost if response else 0,
            web_sources=[item.model_dump(mode="json") for item in response.web_sources] if response else [],
            estimated_cost=response.estimated_cost if response else 0,
            execution_time=attempt.execution_time,
            error=attempt.error,
        ))
    campaign.total_cost = Decimal(campaign.total_cost) + cost


async def _checkpoint(session: AsyncSession, campaign: DiscoveryCampaign) -> None:
    await session.refresh(campaign)
    if campaign.cancellation_requested:
        raise asyncio.CancelledError
    if Decimal(campaign.total_cost) >= Decimal(campaign.max_ai_budget):
        raise DiscoveryBudgetError("O orçamento máximo da campanha foi atingido")


def _founder_data(profile: FounderProfile) -> dict:
    return {
        "name": profile.name,
        "skills": profile.skills,
        "industries": profile.industries,
        "available_capital": str(profile.available_capital),
        "currency": profile.currency,
        "hours_per_week": profile.hours_per_week,
        "target_monthly_revenue": str(profile.target_monthly_revenue),
        "revenue_horizon_days": profile.revenue_horizon_days,
        "preferred_business_models": profile.preferred_business_models,
        "preferred_markets": profile.preferred_markets,
        "distribution_assets": profile.distribution_assets,
        "technologies": profile.technologies,
        "exclusions": profile.exclusions,
        "risk_tolerance": profile.risk_tolerance.value,
    }


def _campaign_data(campaign: DiscoveryCampaign) -> dict:
    return {
        "name": campaign.name,
        "brief": campaign.brief,
        "geography": campaign.geography,
        "language": campaign.language,
        "memory_mode": campaign.memory_mode.value,
        "hard_constraints": _constraints(campaign).model_dump(mode="json"),
        # Legacy campaigns may retain larger stored targets. New executions
        # intentionally cap breadth to spend the budget on evidence quality.
        "candidate_target": min(campaign.candidate_target, 5),
        "finalist_target": min(campaign.finalist_target, 3),
    }


def _signal_data(signal: OpportunitySignal) -> dict:
    return {
        "code": signal.code,
        "pain_statement": signal.pain_statement,
        "audience": signal.audience,
        "observed_signal": signal.observed_signal,
        "commercial_signal": signal.commercial_signal,
        "commercial_strength": signal.commercial_strength,
        "strength": signal.strength,
        "frequency": signal.frequency,
        "willingness_to_pay": signal.willingness_to_pay,
        "source_url": signal.source_url,
    }


def _candidate_data(candidate: OpportunityCandidate, include_research: bool = False) -> dict:
    result = {
        "id": candidate.id,
        "title": candidate.title,
        "problem": candidate.problem,
        "target_customer": candidate.target_customer,
        "solution": candidate.solution,
        "business_model": candidate.business_model,
        "acquisition_channel": candidate.acquisition_channel,
        "pricing_hypothesis": candidate.pricing_hypothesis,
        "first_revenue_path": candidate.first_revenue_path,
        "founder_fit_reason": candidate.founder_fit_reason,
        "signal_codes": candidate.signal_codes,
        "inspired_by_candidate_ids": candidate.inspired_by_candidate_ids,
        "risks": candidate.risks,
        "business_case": candidate.business_case,
    }
    if include_research:
        result["research"] = candidate.research
    return result


async def _recover_generator_opportunities(
    session: AsyncSession,
    campaign: DiscoveryCampaign,
    *,
    known_signal_codes: set[str],
    known_memory_ids: set[str],
) -> list:
    """Recover schema-valid content from a paid attempt rejected by an old invariant."""

    attempts = (await session.scalars(
        select(DiscoveryAgentRun)
        .where(
            DiscoveryAgentRun.campaign_id == campaign.id,
            DiscoveryAgentRun.agent == DiscoveryAgentType.IDEA_GENERATOR,
            DiscoveryAgentRun.output_json.is_not(None),
        )
        .order_by(DiscoveryAgentRun.created_at.desc(), DiscoveryAgentRun.id.desc())
        .limit(10)
    )).all()
    for attempt in attempts:
        try:
            recovered = OpportunityGeneratorOutput.model_validate(attempt.output_json)
        except Exception:
            continue
        valid = []
        for item in recovered.opportunities:
            if not set(item.signal_codes) <= known_signal_codes:
                continue
            # Recover paid content even when the model invented a lineage UUID.
            # Invalid references carry no domain value and are safe to discard.
            item.inspired_by_candidate_ids = [
                candidate_id
                for candidate_id in item.inspired_by_candidate_ids
                if candidate_id in known_memory_ids
            ]
            valid.append(item)
        if len(valid) >= 3:
            return valid[:min(campaign.candidate_target, 5)]
    return []


async def _opportunity_memory(
    session: AsyncSession, campaign: DiscoveryCampaign
) -> dict:
    previous = list((await session.scalars(
        select(OpportunityCandidate)
        .join(DiscoveryCampaign, DiscoveryCampaign.id == OpportunityCandidate.campaign_id)
        .where(
            DiscoveryCampaign.founder_profile_id == campaign.founder_profile_id,
            DiscoveryCampaign.id != campaign.id,
        )
        .order_by(OpportunityCandidate.created_at.desc())
        .limit(120)
    )).all())
    priority = {
        OpportunityFeedbackStatus.APPROVED: 0,
        OpportunityFeedbackStatus.REJECTED: 1,
        OpportunityFeedbackStatus.PENDING: 2,
    }
    previous.sort(
        key=lambda item: (
            priority[item.user_feedback],
            -(item.overall_score or item.preliminary_score or 0),
        )
    )
    memory_items = []
    rejected_tag_counts: dict[str, int] = {}
    for item in previous[:40]:
        research = item.research if isinstance(item.research, dict) else {}
        sources = []
        for key in ("demand_evidence", "competitor_evidence"):
            evidence_list = research.get(key, [])
            if isinstance(evidence_list, list):
                for evidence in evidence_list[:2]:
                    if isinstance(evidence, dict):
                        sources.append({
                            "claim": str(evidence.get("claim", ""))[:280],
                            "source_url": str(evidence.get("source_url", ""))[:1000],
                        })
        memory_items.append({
            "candidate_id": item.id,
            "title": item.title,
            "problem": item.problem[:600],
            "solution": item.solution[:600],
            "score": item.overall_score,
            "confidence": item.confidence,
            "user_feedback": item.user_feedback.value,
            "feedback_tags": item.feedback_tags,
            "feedback_note": (item.feedback_note or "")[:500],
            "research_sources": sources[:4],
        })
        if item.user_feedback == OpportunityFeedbackStatus.REJECTED:
            for tag in item.feedback_tags:
                normalized = tag.strip()
                if normalized:
                    rejected_tag_counts[normalized] = rejected_tag_counts.get(normalized, 0) + 1
    return {
        "mode": campaign.memory_mode.value,
        "instructions": {
            DiscoveryMemoryMode.NEW_ONLY.value: "Avoid all substantially similar prior opportunities.",
            DiscoveryMemoryMode.BALANCED.value: "Never repeat rejected ideas; allow a clearly improved derivative when justified.",
            DiscoveryMemoryMode.IMPROVE_APPROVED.value: "Develop stronger variants of approved ideas and avoid rejected patterns.",
        }[campaign.memory_mode.value],
        "rejected_tag_counts": dict(
            sorted(rejected_tag_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]
        ),
        "items": memory_items,
    }


def _fingerprint(title: str, problem: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", f"{title} {problem}".lower()))


def _similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0


def _deduplicate(items, memory_items: list[dict], mode: DiscoveryMemoryMode):
    unique = []
    fingerprints: list[set[str]] = []
    for item in items:
        words = _fingerprint(item.title, item.problem)
        duplicate = any(_similarity(words, known) >= 0.62 for known in fingerprints)
        if not duplicate:
            for previous in memory_items:
                previous_words = _fingerprint(previous["title"], previous["problem"])
                similarity = _similarity(words, previous_words)
                feedback = previous["user_feedback"]
                if mode == DiscoveryMemoryMode.NEW_ONLY and similarity >= 0.62:
                    duplicate = True
                elif feedback == OpportunityFeedbackStatus.REJECTED.value and similarity >= 0.62:
                    duplicate = True
                elif mode == DiscoveryMemoryMode.BALANCED and similarity >= 0.82:
                    duplicate = True
                elif (
                    mode == DiscoveryMemoryMode.IMPROVE_APPROVED
                    and feedback != OpportunityFeedbackStatus.APPROVED.value
                    and similarity >= 0.82
                ):
                    duplicate = True
                if duplicate:
                    break
        if not duplicate:
            unique.append(item)
            fingerprints.append(words)
    return unique


def _preliminary_score(codes: list[str], signal_map: dict[str, OpportunitySignal]) -> float:
    values = []
    for code in codes:
        signal = signal_map[code]
        values.append((
            signal.strength * 0.30
            + signal.frequency * 0.20
            + signal.willingness_to_pay * 0.25
            + signal.commercial_strength * 0.25
        ) * 20)
    return round(sum(values) / len(values), 2)


def _score_dict(evaluation) -> dict[str, int]:
    return {key: int(getattr(evaluation, key)) for key in (
        "pain_severity", "willingness_to_pay", "reachability", "founder_fit", "economics",
        "speed_to_revenue", "differentiation", "feasibility", "regulatory_safety",
    )}


def _weighted_score(
    scores: dict[str, int],
    market_reality_score: float,
    feedback_adjustment: float = 0,
) -> float:
    weights = {
        "pain_severity": 0.18,
        "willingness_to_pay": 0.16,
        "reachability": 0.14,
        "founder_fit": 0.14,
        "economics": 0.12,
        "speed_to_revenue": 0.10,
        "differentiation": 0.08,
        "feasibility": 0.06,
        "regulatory_safety": 0.02,
    }
    qualitative_score = sum(scores[key] * weight for key, weight in weights.items())
    combined = qualitative_score * 0.75 + market_reality_score * 0.25 + feedback_adjustment
    return round(max(0.0, min(100.0, combined)), 2)


def _constraints(campaign: DiscoveryCampaign) -> DiscoveryHardConstraints:
    raw = campaign.hard_constraints if isinstance(campaign.hard_constraints, dict) else {}
    return DiscoveryHardConstraints.model_validate(raw)


def _hard_constraint_violations(
    business_case: dict[str, object], constraints: DiscoveryHardConstraints
) -> list[str]:
    reasons: list[str] = []
    customer_type = str(business_case.get("customer_type", "ANY"))
    revenue_pattern = str(business_case.get("revenue_pattern", "ONE_OFF"))
    if (
        constraints.customer_type != OpportunityCustomerType.ANY
        and customer_type != constraints.customer_type.value
    ):
        reasons.append(
            f"Regra eliminatória: público {customer_type}, mas a campanha exige {constraints.customer_type.value}."
        )
    if constraints.digital_only and not bool(business_case.get("digital_product")):
        reasons.append("Regra eliminatória: a solução não é um produto digital.")
    if constraints.self_service_only and not bool(business_case.get("self_service")):
        reasons.append("Regra eliminatória: a solução não é self-service.")
    if int(business_case.get("automation_percent", 0)) < constraints.min_automation_percent:
        reasons.append(
            f"Regra eliminatória: automação abaixo de {constraints.min_automation_percent}%."
        )
    if int(business_case.get("mvp_days", 366)) > constraints.max_mvp_days:
        reasons.append(
            f"Regra eliminatória: MVP excede {constraints.max_mvp_days} dias."
        )
    if constraints.exclude_recurring_human_service and bool(
        business_case.get("recurring_human_service")
    ):
        reasons.append("Regra eliminatória: exige operação humana recorrente.")
    if constraints.exclude_regulated_advice and bool(business_case.get("regulated_advice")):
        reasons.append("Regra eliminatória: depende de aconselhamento regulado.")
    if constraints.exclude_two_sided_marketplaces and bool(business_case.get("two_sided_marketplace")):
        reasons.append("Regra eliminatória: depende de marketplace de dois lados.")
    if constraints.require_recurring_or_repeat_revenue and revenue_pattern not in {
        OpportunityRevenuePattern.RECURRING.value,
        OpportunityRevenuePattern.REPEAT.value,
    }:
        reasons.append("Regra eliminatória: não possui recorrência ou recompra clara.")
    return reasons


def _has_market_research(research: object) -> bool:
    return isinstance(research, dict) and "evidence_quality_score" in research


def _market_reality_score(analysis) -> float:
    weights = {
        "demand_signal_score": 0.25,
        "willingness_to_pay_score": 0.20,
        "paid_competitor_score": 0.15,
        "channel_score": 0.15,
        "recurrence_score": 0.10,
        "margin_score": 0.10,
        "evidence_quality_score": 0.05,
    }
    return round(sum(float(getattr(analysis, key)) * weight for key, weight in weights.items()), 2)


def _market_gate_failures(
    analysis,
    market_score: float,
    constraints: DiscoveryHardConstraints,
) -> list[str]:
    reasons: list[str] = []
    demand_sources = len({item.source_url for item in analysis.demand_evidence})
    competitor_sources = len({
        item.source_url
        for item in analysis.competitor_evidence
        if item.supports_purchase_behavior
    })
    if demand_sources < constraints.min_demand_sources:
        reasons.append(
            f"Mercado: apenas {demand_sources} de {constraints.min_demand_sources} fontes independentes de demanda."
        )
    paid_competitors = min(analysis.paid_competitor_count, competitor_sources)
    if paid_competitors < constraints.min_paid_competitors:
        reasons.append(
            f"Mercado: apenas {paid_competitors} de {constraints.min_paid_competitors} concorrentes pagos comprovados."
        )
    if constraints.require_reachable_channel and analysis.channel_score < 50:
        reasons.append("Mercado: nenhum canal de aquisição suficientemente acessível foi comprovado.")
    if market_score < constraints.min_market_reality_score:
        reasons.append(
            f"Mercado: Market Reality Score {market_score:.1f} abaixo do mínimo {constraints.min_market_reality_score}."
        )
    return reasons


def _feedback_adjustment(candidate, evaluation, opportunity_memory: dict) -> tuple[float, list[str]]:
    known_rejections = set(opportunity_memory.get("rejected_tag_counts", {}))
    matched = {tag for tag in evaluation.matched_rejection_tags if tag in known_rejections}
    business_case = candidate.business_case if isinstance(candidate.business_case, dict) else {}
    deterministic_conflicts = {
        "B2B": str(business_case.get("customer_type")) == OpportunityCustomerType.B2B.value,
        "Operação manual": bool(business_case.get("recurring_human_service")),
        "Risco regulatório": bool(business_case.get("regulated_advice")),
        "Baixa recorrência": str(business_case.get("revenue_pattern")) == OpportunityRevenuePattern.ONE_OFF.value,
        "Sem disposição a pagar": evaluation.willingness_to_pay < 50,
        "Sem canal de aquisição": evaluation.reachability < 50,
        "Venda difícil": evaluation.reachability < 50,
        "Custo alto": evaluation.economics < 50,
        "Pouco diferencial": evaluation.differentiation < 50,
        "Fácil de copiar": evaluation.differentiation < 50,
        "Complexa demais": evaluation.feasibility < 50,
        "Não combina comigo": evaluation.founder_fit < 50,
    }
    matched.update(
        tag for tag, applies in deterministic_conflicts.items() if applies and tag in known_rejections
    )
    penalty = min(25.0, len(matched) * 8.0)
    approved_ids = {
        item["candidate_id"]
        for item in opportunity_memory.get("items", [])
        if item.get("user_feedback") == OpportunityFeedbackStatus.APPROVED.value
    }
    approval_bonus = 5.0 if set(candidate.inspired_by_candidate_ids) & approved_ids else 0.0
    return approval_bonus - penalty, sorted(matched)
