from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError
from app.agents.researcher import ResearcherAgent
from app.core.config import get_settings
from app.database.models import Criticism, Hypothesis
from app.domain.enums import AgentType, HypothesisOrigin, HypothesisStatus
from app.llm.base import LLMProvider, WebSearchConfig
from app.schemas.research import ResearcherOutput
from app.services.agent_runs import add_agent_runs
from app.services.budget import require_budget_available
from app.services.context_compaction import (
    compact_accumulated_context,
    compact_concept,
    compact_records,
)
from app.services.errors import AgentExecutionFailedError
from app.services.knowledge import (
    list_evidence,
    list_hypotheses,
    register_concept_hypotheses,
    register_web_sources,
)
from app.services.project_context import get_project_and_latest_version
from app.services.prompts import get_effective_prompt


async def run_researcher(
    session: AsyncSession,
    project_id: UUID,
    provider: LLMProvider,
    *,
    round_id: str | None = None,
    user_context: str | None = None,
    accumulated_context: dict[str, Any] | None = None,
    workflow_stage: str = "INDEPENDENT",
) -> ResearcherOutput:
    project, current_version = await get_project_and_latest_version(session, project_id)
    require_budget_available(project)
    hypotheses = await list_hypotheses(session, project_id)
    if not hypotheses:
        await register_concept_hypotheses(
            session,
            project_id=project.id,
            source_version_id=current_version.id,
            concept=current_version.concept,
            origin=HypothesisOrigin.RESEARCHER,
        )
        await session.commit()
        hypotheses = await list_hypotheses(session, project_id)
    if not hypotheses:
        await register_concept_hypotheses(
            session,
            project_id=project.id,
            source_version_id=current_version.id,
            concept={},
            origin=HypothesisOrigin.RESEARCHER,
            additional_hypotheses=(
                "Existe demanda real e disposição de pagar pela proposta central.",
            ),
        )
        await session.commit()
        hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    criticisms = list(
        (
            await session.scalars(
                select(Criticism)
                .where(Criticism.project_id == project.id)
                .order_by(Criticism.created_at.asc(), Criticism.id.asc())
            )
        ).all()
    )
    research_target = _select_research_target(hypotheses, criticisms, workflow_stage)
    target_evidence = [
        item for item in evidence if item.hypothesis_id == research_target.id
    ]
    target_criticisms = [
        item
        for item in criticisms
        if not item.affected_hypotheses
        or research_target.id in item.affected_hypotheses
    ]
    settings = get_settings()
    effective_prompt = await get_effective_prompt(session, AgentType.RESEARCHER)
    web_search = None
    if settings.research_web_enabled and provider.supports_web_search:
        web_search = WebSearchConfig(
            max_calls=settings.research_web_max_calls,
            context_size=settings.research_web_context_size,
        )
    agent = ResearcherAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
        web_search=web_search,
    )

    try:
        result = await agent.run(
            current_concept=compact_concept(current_version.concept),
            research_target=research_target.model_dump(mode="json"),
            hypotheses=compact_records(
                [research_target.model_dump(mode="json")], limit=1
            ),
            evidence=compact_records(
                [item.model_dump(mode="json") for item in target_evidence], limit=12
            ),
            criticisms=compact_records(
                [_criticism_input(item) for item in target_criticisms], limit=8
            ),
            unanswered_questions=list(current_version.concept.get("unknowns", [])),
            accumulated_context=compact_accumulated_context(accumulated_context),
            workflow_stage=workflow_stage,
            user_context=user_context,
        )
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=project.id,
            agent=AgentType.RESEARCHER,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
            round_id=round_id,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=AgentType.RESEARCHER.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    runs = await add_agent_runs(
        session,
        project_id=project.id,
        agent=AgentType.RESEARCHER,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
        round_id=round_id,
    )
    await session.flush()
    successful_attempt = result.attempts[-1]
    response = successful_attempt.response
    output = result.output
    if response is not None and response.web_sources:
        registered = await register_web_sources(
            session,
            project_id=project.id,
            hypothesis_code=research_target.id,
            agent_run_id=runs[-1].id,
            question=output.question,
            finding=output.finding,
            sources=response.web_sources,
        )
        evidence_ids = list(
            dict.fromkeys([*output.evidence, *(item.id for item in registered)])
        )
        output = output.model_copy(update={"evidence": evidence_ids})
        runs[-1].output_json = output.model_dump(mode="json")
    if output.evidence or (response is not None and response.web_sources):
        target_row = await session.scalar(
            select(Hypothesis).where(
                Hypothesis.project_id == project.id,
                Hypothesis.sequence == int(research_target.id[1:]),
            )
        )
        if target_row is not None:
            target_row.status = HypothesisStatus.PARTIAL
            target_row.confidence = max(
                target_row.confidence,
                min(float(output.confidence), 0.8),
            )
    await session.commit()
    return output


def _criticism_input(criticism: Criticism) -> dict[str, Any]:
    return {
        "title": criticism.title,
        "severity": criticism.severity.value,
        "claim": criticism.claim,
        "reason": criticism.reason,
        "affected_hypotheses": criticism.affected_hypotheses,
        "evidence_needed": criticism.evidence_needed,
        "condition_that_refutes_criticism": criticism.condition_that_refutes_criticism,
    }


def _select_research_target(hypotheses, criticisms, workflow_stage: str):
    open_items = [
        item
        for item in hypotheses
        if item.status in {HypothesisStatus.OPEN, HypothesisStatus.PARTIAL}
    ] or list(hypotheses)
    criticized = {
        code
        for criticism in criticisms
        for code in criticism.affected_hypotheses
    }
    return min(
        open_items,
        key=lambda item: (
            -int(workflow_stage == "CRITIC_VERIFICATION" and item.id in criticized),
            len(item.evidence_ids),
            -item.priority,
            item.id,
        ),
    )
