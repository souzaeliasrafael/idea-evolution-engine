from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError
from app.agents.judge import JudgeAgent
from app.core.config import get_settings
from app.database.models import (
    AgentRun,
    Criticism,
    DecisionRecord,
    Project,
    ProjectScore,
)
from app.domain.enums import AgentType
from app.llm.base import LLMProvider
from app.orchestration.stagnation import StagnationDetector
from app.schemas.judgment import DecisionRead, JudgeOutput
from app.scoring.engine import ScoreEngine
from app.services.agent_runs import add_agent_runs
from app.services.budget import require_budget_available
from app.services.context_compaction import (
    compact_accumulated_context,
    compact_concept,
    compact_records,
)
from app.services.errors import AgentExecutionFailedError, ProjectNotFoundError
from app.services.project_context import get_project_and_latest_version
from app.services.knowledge import list_evidence, list_hypotheses
from app.services.experiments import experiment_context
from app.services.human_review import review_status_for
from app.services.prompts import get_effective_prompt


async def run_judge(
    session: AsyncSession,
    project_id: UUID,
    provider: LLMProvider,
    *,
    round_id: str | None = None,
    round_number: int | None = None,
    user_context: str | None = None,
    accumulated_context: dict[str, Any] | None = None,
) -> JudgeOutput:
    project, current_version = await get_project_and_latest_version(session, project_id)
    require_budget_available(project)
    criticisms = list(
        (
            await session.scalars(
                select(Criticism)
                .where(Criticism.project_id == project.id)
                .order_by(Criticism.created_at.asc(), Criticism.id.asc())
            )
        ).all()
    )
    previous_scores = list(
        (
            await session.scalars(
                select(ProjectScore)
                .where(ProjectScore.project_id == project.id)
                .order_by(ProjectScore.created_at.asc(), ProjectScore.id.asc())
            )
        ).all()
    )
    previous_decisions = list(
        (
            await session.scalars(
                select(DecisionRecord)
                .where(DecisionRecord.project_id == project.id)
                .order_by(DecisionRecord.created_at.asc(), DecisionRecord.id.asc())
            )
        ).all()
    )
    hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    latest_research = await _latest_research_output(
        session, project.id, round_id=round_id
    )
    experiments = await experiment_context(session, project.id)
    effective_prompt = await get_effective_prompt(session, AgentType.JUDGE)
    settings = get_settings()
    agent = JudgeAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
    )
    stagnation_before_run = StagnationDetector.detect(
        [item.total_score for item in previous_scores]
    )

    try:
        result = await agent.run(
            current_concept=compact_concept(current_version.concept),
            criticisms=compact_records(
                [_criticism_input(item) for item in criticisms], limit=50
            ),
            hypotheses=compact_records(
                [item.model_dump(mode="json") for item in hypotheses], limit=100
            ),
            evidence=compact_records(
                [item.model_dump(mode="json") for item in evidence], limit=80
            ),
            latest_research=latest_research,
            accumulated_context=compact_accumulated_context(accumulated_context),
            experiments=experiments,
            previous_scores=compact_records(
                [_score_input(item) for item in previous_scores], limit=20
            ),
            previous_decisions=compact_records(
                [_decision_input(item) for item in previous_decisions], limit=20
            ),
            stagnation_detected=stagnation_before_run,
            user_context=user_context,
        )
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=project.id,
            agent=AgentType.JUDGE,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
            round_id=round_id,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=AgentType.JUDGE.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    runs = await add_agent_runs(
        session,
        project_id=project.id,
        agent=AgentType.JUDGE,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
        round_id=round_id,
    )
    await session.flush()
    successful_run = runs[-1]
    calculation = ScoreEngine.calculate(result.output.criteria)
    score = ProjectScore(
        project_id=project.id,
        idea_version_id=current_version.id,
        agent_run_id=successful_run.id,
        total_score=calculation.total_score,
        confidence=result.output.confidence,
        breakdown=[item.model_dump(mode="json") for item in calculation.breakdown],
    )
    session.add(score)
    await session.flush()
    stagnation_after_run = StagnationDetector.detect(
        [item.total_score for item in previous_scores] + [calculation.total_score]
    )
    project.stagnation_detected = (
        project.stagnation_detected or stagnation_after_run
    )
    session.add(
        DecisionRecord(
            project_id=project.id,
            round_number=round_number,
            decision=result.output.decision,
            reason=result.output.reasoning_summary,
            from_version_id=current_version.id,
            to_version_id=None,
            score_id=score.id,
            agent_run_id=successful_run.id,
            critical_blockers=result.output.critical_blockers,
            most_important_unknowns=result.output.most_important_unknowns,
            next_actions=result.output.next_actions,
            human_review_status=review_status_for(result.output.decision),
        )
    )
    await session.commit()
    return JudgeOutput(
        decision=result.output.decision,
        score=calculation.total_score,
        confidence=result.output.confidence,
        reasoning_summary=result.output.reasoning_summary,
        critical_blockers=result.output.critical_blockers,
        most_important_unknowns=result.output.most_important_unknowns,
        next_actions=result.output.next_actions,
        score_breakdown=calculation.breakdown,
        stagnation_detected=stagnation_after_run,
    )


async def list_scores(
    session: AsyncSession, project_id: UUID
) -> Sequence[ProjectScore]:
    await _require_project(session, project_id)
    result = await session.scalars(
        select(ProjectScore)
        .where(ProjectScore.project_id == str(project_id))
        .order_by(ProjectScore.created_at.asc(), ProjectScore.id.asc())
    )
    return result.all()


async def list_decisions(
    session: AsyncSession, project_id: UUID
) -> list[DecisionRead]:
    await _require_project(session, project_id)
    rows = (
        await session.execute(
            select(DecisionRecord, ProjectScore)
            .join(ProjectScore, DecisionRecord.score_id == ProjectScore.id)
            .where(DecisionRecord.project_id == str(project_id))
            .order_by(DecisionRecord.created_at.asc(), DecisionRecord.id.asc())
        )
    ).all()
    return [
        DecisionRead(
            id=decision.id,
            project_id=decision.project_id,
            round_number=decision.round_number,
            decision=decision.decision,
            reason=decision.reason,
            from_version_id=decision.from_version_id,
            to_version_id=decision.to_version_id,
            score_id=decision.score_id,
            score=score.total_score,
            confidence=score.confidence,
            critical_blockers=decision.critical_blockers,
            most_important_unknowns=decision.most_important_unknowns,
            next_actions=decision.next_actions,
            human_review_status=decision.human_review_status,
            human_action=decision.human_action,
            human_note=decision.human_note,
            reviewed_at=decision.reviewed_at,
            created_at=decision.created_at,
        )
        for decision, score in rows
    ]


async def _require_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


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


def _score_input(score: ProjectScore) -> dict[str, Any]:
    return {
        "score": score.total_score,
        "confidence": score.confidence,
        "breakdown": score.breakdown,
    }


def _decision_input(decision: DecisionRecord) -> dict[str, Any]:
    return {
        "decision": decision.decision.value,
        "reason": decision.reason,
        "critical_blockers": decision.critical_blockers,
        "most_important_unknowns": decision.most_important_unknowns,
        "next_actions": decision.next_actions,
    }


async def _latest_research_output(
    session: AsyncSession, project_id: str, *, round_id: str | None
) -> dict[str, Any] | None:
    query = (
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
    if round_id is not None:
        query = query.where(AgentRun.round_id == round_id)
    return await session.scalar(query)
