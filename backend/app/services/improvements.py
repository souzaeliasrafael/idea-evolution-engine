from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError
from app.agents.improver import ImproverAgent
from app.core.config import get_settings
from app.database.models import (
    AgentRun,
    Criticism,
    DecisionRecord,
    ImprovementPlan,
    Project,
    ProjectScore,
)
from app.domain.enums import AgentType
from app.llm.base import LLMProvider
from app.services.agent_runs import add_agent_runs
from app.services.budget import require_budget_available
from app.services.context_compaction import compact_concept, compact_records
from app.services.errors import (
    AgentExecutionFailedError,
    ProjectNotEvaluatedError,
    ProjectNotFoundError,
)
from app.services.knowledge import list_evidence, list_hypotheses
from app.services.project_context import get_project_and_latest_version
from app.services.prompts import get_effective_prompt


async def run_improver(
    session: AsyncSession,
    project_id: UUID,
    provider: LLMProvider,
    *,
    round_id: str | None = None,
    decision_id: str | None = None,
    user_context: str | None = None,
) -> ImprovementPlan:
    project, current_version = await get_project_and_latest_version(session, project_id)
    require_budget_available(project)
    decision, score = await _source_assessment(session, project.id, decision_id)
    criticisms = list(
        (
            await session.scalars(
                select(Criticism)
                .where(Criticism.project_id == project.id)
                .order_by(Criticism.created_at.asc(), Criticism.id.asc())
            )
        ).all()
    )
    scores = list(
        (
            await session.scalars(
                select(ProjectScore)
                .where(ProjectScore.project_id == project.id)
                .order_by(ProjectScore.created_at.asc(), ProjectScore.id.asc())
            )
        ).all()
    )
    hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    previous_plans = list(
        (
            await session.scalars(
                select(ImprovementPlan)
                .where(ImprovementPlan.project_id == project.id)
                .order_by(ImprovementPlan.version.desc())
                .limit(5)
            )
        ).all()
    )
    effective_prompt = await get_effective_prompt(session, AgentType.IMPROVER)
    settings = get_settings()
    agent = ImproverAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
    )
    try:
        result = await agent.run(
            current_concept=compact_concept(current_version.concept),
            latest_score=_score_input(score),
            latest_decision=_decision_input(decision),
            criticisms=compact_records(
                [_criticism_input(item) for item in criticisms], limit=50
            ),
            hypotheses=compact_records(
                [item.model_dump(mode="json") for item in hypotheses], limit=100
            ),
            evidence=compact_records(
                [item.model_dump(mode="json") for item in evidence], limit=80
            ),
            latest_research=await _latest_research_output(session, project.id),
            score_history=compact_records(
                [_score_input(item) for item in scores], limit=20
            ),
            previous_plans=compact_records(
                [item.plan for item in reversed(previous_plans)], limit=5
            ),
            user_context=user_context,
        )
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=project.id,
            agent=AgentType.IMPROVER,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
            round_id=round_id,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=AgentType.IMPROVER.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    runs = await add_agent_runs(
        session,
        project_id=project.id,
        agent=AgentType.IMPROVER,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
        round_id=round_id,
    )
    await session.flush()
    current_version_number = await session.scalar(
        select(func.max(ImprovementPlan.version)).where(
            ImprovementPlan.project_id == project.id
        )
    )
    plan = ImprovementPlan(
        project_id=project.id,
        round_id=round_id,
        idea_version_id=current_version.id,
        score_id=score.id,
        decision_id=decision.id,
        agent_run_id=runs[-1].id,
        version=int(current_version_number or 0) + 1,
        source_score=score.total_score,
        source_confidence=score.confidence,
        plan=result.output.model_dump(mode="json"),
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def list_improvement_plans(
    session: AsyncSession, project_id: UUID
) -> Sequence[ImprovementPlan]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    return (
        await session.scalars(
            select(ImprovementPlan)
            .where(ImprovementPlan.project_id == str(project_id))
            .order_by(ImprovementPlan.version.desc())
        )
    ).all()


async def latest_improvement_plan(
    session: AsyncSession, project_id: str
) -> ImprovementPlan | None:
    return await session.scalar(
        select(ImprovementPlan)
        .where(ImprovementPlan.project_id == project_id)
        .order_by(ImprovementPlan.version.desc())
        .limit(1)
    )


async def _source_assessment(
    session: AsyncSession, project_id: str, decision_id: str | None
) -> tuple[DecisionRecord, ProjectScore]:
    query = (
        select(DecisionRecord, ProjectScore)
        .join(ProjectScore, DecisionRecord.score_id == ProjectScore.id)
        .where(DecisionRecord.project_id == project_id)
    )
    if decision_id is not None:
        query = query.where(DecisionRecord.id == decision_id)
    query = query.order_by(
        DecisionRecord.created_at.desc(), DecisionRecord.id.desc()
    ).limit(1)
    row = (await session.execute(query)).first()
    if row is None:
        raise ProjectNotEvaluatedError(project_id)
    return row[0], row[1]


async def _latest_research_output(
    session: AsyncSession, project_id: str
) -> dict[str, Any] | None:
    return await session.scalar(
        select(AgentRun.output_json)
        .where(
            AgentRun.project_id == project_id,
            AgentRun.agent == AgentType.RESEARCHER,
            AgentRun.error.is_(None),
            AgentRun.output_json.is_not(None),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


def _score_input(score: ProjectScore) -> dict[str, Any]:
    return {
        "id": score.id,
        "score": score.total_score,
        "confidence": score.confidence,
        "breakdown": score.breakdown,
    }


def _decision_input(decision: DecisionRecord) -> dict[str, Any]:
    return {
        "id": decision.id,
        "decision": decision.decision.value,
        "reason": decision.reason,
        "critical_blockers": decision.critical_blockers,
        "most_important_unknowns": decision.most_important_unknowns,
        "next_actions": decision.next_actions,
    }


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
