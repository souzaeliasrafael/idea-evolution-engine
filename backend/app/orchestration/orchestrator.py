import asyncio
from collections.abc import Sequence
from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.models import (
    AgentRun,
    DecisionRecord,
    IdeaVersion,
    Project,
    ProjectScore,
    Round,
    utc_now,
)
from app.domain.enums import (
    AgentType,
    DecisionType,
    HumanReviewAction,
    HumanReviewStatus,
    OrchestratorStopReason,
    ProjectStatus,
    RoundStatus,
)
from app.llm.router import LLMRouter
from app.orchestration.rules import (
    require_non_terminal_project,
    validate_round_limit,
)
from app.orchestration.progress import workflow_progress
from app.orchestration.transitions import (
    status_for_round_start,
    transition_for,
)
from app.schemas.judgment import JudgeOutput
from app.schemas.orchestration import OrchestratorRunResult, RoundRead
from app.schemas.project import AgentExecutionPlan
from app.services import evaluation as evaluation_service
from app.services import experiments as experiment_service
from app.services import human_review as human_review_service
from app.services import improvements as improvement_service
from app.services import judging as judging_service
from app.services import research as research_service
from app.services import structuring as structuring_service
from app.services.errors import (
    AgentExecutionFailedError,
    BudgetLimitReachedError,
    OrchestratorAlreadyRunningError,
    ProjectNotFoundError,
    WorkflowCancellationRequested,
)
from app.services.project_context import get_project_and_latest_version


async def run_project(
    session: AsyncSession,
    project_id: UUID,
    llm_router: LLMRouter,
    *,
    max_rounds: int,
) -> OrchestratorRunResult:
    settings = get_settings()
    validate_round_limit(max_rounds, settings.max_rounds)
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    require_non_terminal_project(project.status)
    await human_review_service.require_no_pending_review(session, project.id)
    await experiment_service.require_no_open_experiments(session, project.id)
    if project.status == ProjectStatus.STRUCTURING:
        raise OrchestratorAlreadyRunningError(project.id)
    await _require_no_running_round(session, project.id)
    agent_plan = AgentExecutionPlan.model_validate(project.agent_plan)

    if not await _has_idea_version(session, project.id):
        previous_status = project.status
        project.status = ProjectStatus.STRUCTURING
        await session.commit()
        try:
            workflow_progress.set_agent(
                project_id,
                AgentType.STRUCTURER,
                current_round=None,
                round_position=None,
                workflow_stage="Estruturação inicial",
            )
            if workflow_progress.cancellation_requested(project_id):
                project.status = previous_status
                await session.commit()
                return _result(
                    project,
                    [],
                    None,
                    OrchestratorStopReason.USER_CANCELLED,
                )
            await structuring_service.structure_project(
                session,
                project_id,
                llm_router.provider_for(AgentType.STRUCTURER),
            )
        except asyncio.CancelledError:
            await session.rollback()
            project = await session.get(Project, str(project_id))
            if project is None:
                raise ProjectNotFoundError(str(project_id))
            if not await _has_idea_version(session, project.id):
                project.status = previous_status
                await session.commit()
            return _result(
                project, [], None, OrchestratorStopReason.USER_CANCELLED
            )
        except Exception:
            await session.rollback()
            project = await session.get(Project, str(project_id))
            if (
                project is not None
                and not await _has_idea_version(session, project.id)
            ):
                project.status = previous_status
                await session.commit()
            raise

    if workflow_progress.cancellation_requested(project_id):
        if project.status == ProjectStatus.STRUCTURING:
            project.status = ProjectStatus.DRAFT
            await session.commit()
        return _result(
            project,
            [],
            None,
            OrchestratorStopReason.USER_CANCELLED,
        )

    previous_decision = await _latest_decision(session, project.id)
    previous_score = await _latest_score(session, project.id)
    previous_score_value = (
        previous_score.total_score if previous_score is not None else None
    )
    previous_confidence = (
        previous_score.confidence if previous_score is not None else None
    )
    previous_improvement_plan = await improvement_service.latest_improvement_plan(
        session, project.id
    )
    await session.refresh(project, attribute_names=["next_round_context"])
    pending_context = project.next_round_context
    next_round_number = await _next_round_number(session, project.id)
    completed_rounds: list[RoundRead] = []
    final_output: JudgeOutput | None = None

    for offset in range(max_rounds):
        if workflow_progress.cancellation_requested(project_id):
            return _result(
                project,
                completed_rounds,
                final_output,
                OrchestratorStopReason.USER_CANCELLED,
            )
        _, starting_version = await get_project_and_latest_version(session, project_id)
        round_number = next_round_number + offset
        round_context = pending_context if offset == 0 else None
        round_record = Round(
            project_id=project.id,
            round_number=round_number,
            status=RoundStatus.RUNNING,
            starting_version_id=starting_version.id,
            human_context=round_context,
        )
        project.status = status_for_round_start(
            previous_decision.decision if previous_decision is not None else None
        )
        session.add(round_record)
        await session.commit()
        await session.refresh(round_record)

        try:
            round_agent_plan = adaptive_agent_plan(
                agent_plan,
                previous_score=previous_score_value,
                previous_confidence=previous_confidence,
                enabled=settings.adaptive_agent_depth_enabled,
                score_threshold=settings.adaptive_depth_score_threshold,
                confidence_threshold=settings.adaptive_depth_confidence_threshold,
            )
            round_instruction = _decision_instruction(
                previous_decision,
                previous_improvement_plan.plan
                if previous_improvement_plan is not None
                else None,
            )
            accumulated_context: dict[str, object] = {
                "round_number": round_number,
                "previous_decision": round_instruction,
                "previous_improvement_plan": (
                    previous_improvement_plan.plan
                    if previous_improvement_plan is not None
                    else None
                ),
                "events": [],
            }
            events = accumulated_context["events"]
            if not isinstance(events, list):
                raise RuntimeError("Round memory events must be a list")
            recovered_failures: list[str] = []

            for iteration in range(round_agent_plan.researcher):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.RESEARCHER,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=iteration + 1,
                    agent_iterations=round_agent_plan.researcher,
                    workflow_stage="Pesquisa inicial",
                )
                try:
                    output = await research_service.run_researcher(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.RESEARCHER),
                        round_id=round_record.id,
                        user_context=round_context,
                        accumulated_context=deepcopy(accumulated_context),
                        workflow_stage="DISCOVERY",
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures, events, exc, "DISCOVERY", iteration + 1
                    )
                    continue
                events.append(
                    {
                        "agent": AgentType.RESEARCHER.value,
                        "stage": "DISCOVERY",
                        "output": output.model_dump(mode="json"),
                    }
                )

            for iteration in range(round_agent_plan.builder):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.BUILDER,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=iteration + 1,
                    agent_iterations=round_agent_plan.builder,
                    workflow_stage="Enriquecimento após pesquisa",
                )
                try:
                    output = await evaluation_service.run_builder(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.BUILDER),
                        round_id=round_record.id,
                        workflow_instruction=round_instruction,
                        user_context=round_context,
                        accumulated_context=deepcopy(accumulated_context),
                        workflow_stage="POST_RESEARCH_ENRICHMENT",
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures,
                        events,
                        exc,
                        "POST_RESEARCH_ENRICHMENT",
                        iteration + 1,
                    )
                    if _is_output_truncation(exc):
                        break
                    continue
                events.append(
                    {
                        "agent": AgentType.BUILDER.value,
                        "stage": "POST_RESEARCH_ENRICHMENT",
                        "output": output.model_dump(mode="json"),
                    }
                )

            for iteration in range(round_agent_plan.critic):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.CRITIC,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=iteration + 1,
                    agent_iterations=round_agent_plan.critic,
                    workflow_stage="Crítica do conteúdo acumulado",
                )
                try:
                    output = await evaluation_service.run_critic(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.CRITIC),
                        round_id=round_record.id,
                        user_context=round_context,
                        accumulated_context=deepcopy(accumulated_context),
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures,
                        events,
                        exc,
                        "ACCUMULATED_REVIEW",
                        iteration + 1,
                    )
                    continue
                events.append(
                    {
                        "agent": AgentType.CRITIC.value,
                        "stage": "ACCUMULATED_REVIEW",
                        "output": output.model_dump(mode="json"),
                    }
                )

            for iteration in range(round_agent_plan.researcher):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.RESEARCHER,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=iteration + 1,
                    agent_iterations=round_agent_plan.researcher,
                    workflow_stage="Verificação das críticas",
                )
                try:
                    output = await research_service.run_researcher(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.RESEARCHER),
                        round_id=round_record.id,
                        user_context=round_context,
                        accumulated_context=deepcopy(accumulated_context),
                        workflow_stage="CRITIC_VERIFICATION",
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures,
                        events,
                        exc,
                        "CRITIC_VERIFICATION",
                        iteration + 1,
                    )
                    continue
                events.append(
                    {
                        "agent": AgentType.RESEARCHER.value,
                        "stage": "CRITIC_VERIFICATION",
                        "output": output.model_dump(mode="json"),
                    }
                )

            for iteration in range(round_agent_plan.builder):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.BUILDER,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=iteration + 1,
                    agent_iterations=round_agent_plan.builder,
                    workflow_stage="Enriquecimento final",
                )
                try:
                    output = await evaluation_service.run_builder(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.BUILDER),
                        round_id=round_record.id,
                        workflow_instruction=round_instruction,
                        user_context=round_context,
                        accumulated_context=deepcopy(accumulated_context),
                        workflow_stage="FINAL_ENRICHMENT",
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures,
                        events,
                        exc,
                        "FINAL_ENRICHMENT",
                        iteration + 1,
                    )
                    if _is_output_truncation(exc):
                        break
                    continue
                events.append(
                    {
                        "agent": AgentType.BUILDER.value,
                        "stage": "FINAL_ENRICHMENT",
                        "output": output.model_dump(mode="json"),
                    }
                )

            if round_agent_plan.builder:
                _, resulting_version = await get_project_and_latest_version(
                    session, project_id
                )
                round_record.resulting_version_id = resulting_version.id
                _link_previous_decision(previous_decision, resulting_version.id)

            _require_not_cancelled(project_id)
            workflow_progress.set_agent(
                project_id,
                AgentType.JUDGE,
                current_round=round_number,
                round_position=offset + 1,
                agent_iteration=1,
                agent_iterations=1,
                workflow_stage="Julgamento final",
            )
            final_output = await judging_service.run_judge(
                session,
                project_id,
                llm_router.provider_for(AgentType.JUDGE),
                round_id=round_record.id,
                round_number=round_number,
                user_context=round_context,
                accumulated_context=deepcopy(accumulated_context),
            )
            decision = await _round_decision(session, round_record.id)
            transition = transition_for(final_output.decision)
            if final_output.decision == DecisionType.TEST:
                await experiment_service.ensure_experiment_for_decision(
                    session, decision
                )

            generated_improvement_plan = None
            await session.refresh(project)
            if (
                final_output.decision not in {DecisionType.APPROVE, DecisionType.DISCARD}
                and not project.budget_exhausted
            ):
                _require_not_cancelled(project_id)
                workflow_progress.set_agent(
                    project_id,
                    AgentType.IMPROVER,
                    current_round=round_number,
                    round_position=offset + 1,
                    agent_iteration=1,
                    agent_iterations=1,
                    workflow_stage="Plano de melhoria",
                )
                try:
                    generated_improvement_plan = await improvement_service.run_improver(
                        session,
                        project_id,
                        llm_router.provider_for(AgentType.IMPROVER),
                        round_id=round_record.id,
                        decision_id=decision.id,
                        user_context=round_context,
                    )
                except AgentExecutionFailedError as exc:
                    _record_recovered_failure(
                        recovered_failures,
                        events,
                        exc,
                        "POST_JUDGE_IMPROVEMENT",
                        1,
                    )

            round_record.status = RoundStatus.COMPLETED
            round_record.decision = final_output.decision
            round_record.score = final_output.score
            round_record.confidence = final_output.confidence
            round_record.stagnation_detected = final_output.stagnation_detected
            if recovered_failures:
                round_record.error = "Recovered agent failures: " + " | ".join(
                    recovered_failures
                )
            round_record.completed_at = utc_now()
            project.status = transition.project_status
            if round_context is not None:
                await session.refresh(project, attribute_names=["next_round_context"])
                if project.next_round_context == round_context:
                    project.next_round_context = None
            await session.commit()
            await session.refresh(round_record)
            completed_rounds.append(RoundRead.model_validate(round_record))

            if not transition.continue_run:
                return _result(
                    project,
                    completed_rounds,
                    final_output,
                    transition.stop_reason,
                )
            if project.budget_exhausted:
                return _result(
                    project,
                    completed_rounds,
                    final_output,
                    OrchestratorStopReason.BUDGET_LIMIT_REACHED,
                )
            if workflow_progress.cancellation_requested(project_id):
                return _result(
                    project,
                    completed_rounds,
                    final_output,
                    OrchestratorStopReason.USER_CANCELLED,
                )
            previous_decision = decision
            previous_score_value = final_output.score
            previous_confidence = final_output.confidence
            if generated_improvement_plan is not None:
                previous_improvement_plan = generated_improvement_plan
        except (WorkflowCancellationRequested, asyncio.CancelledError):
            if round_record.resulting_version_id is None:
                _, latest_version = await get_project_and_latest_version(
                    session, project_id
                )
                if latest_version.id != round_record.starting_version_id:
                    round_record.resulting_version_id = latest_version.id
                    _link_previous_decision(previous_decision, latest_version.id)
            round_record.status = RoundStatus.CANCELLED
            round_record.error = "Stopped by user"
            round_record.completed_at = utc_now()
            await session.commit()
            await session.refresh(round_record)
            completed_rounds.append(RoundRead.model_validate(round_record))
            return _result(
                project,
                completed_rounds,
                final_output,
                OrchestratorStopReason.USER_CANCELLED,
            )
        except BudgetLimitReachedError:
            if round_record.resulting_version_id is None:
                _, latest_version = await get_project_and_latest_version(
                    session, project_id
                )
                if latest_version.id != round_record.starting_version_id:
                    round_record.resulting_version_id = latest_version.id
                    _link_previous_decision(previous_decision, latest_version.id)
            round_record.status = RoundStatus.COMPLETED
            round_record.budget_limit_reached = True
            round_record.completed_at = utc_now()
            await session.commit()
            await session.refresh(round_record)
            completed_rounds.append(RoundRead.model_validate(round_record))
            return _result(
                project,
                completed_rounds,
                final_output,
                OrchestratorStopReason.BUDGET_LIMIT_REACHED,
            )
        except Exception as exc:
            await session.rollback()
            failed_round = await session.get(Round, round_record.id)
            if failed_round is not None:
                failed_round.status = RoundStatus.FAILED
                failed_round.error = f"{type(exc).__name__}: {exc}"[:2000]
                failed_round.completed_at = utc_now()
                await session.commit()
            raise

    if final_output is None:
        raise RuntimeError("Orchestrator completed no rounds")
    return _result(
        project,
        completed_rounds,
        final_output,
        OrchestratorStopReason.MAX_ROUNDS_REACHED,
    )


async def cancelled_run_result(
    session: AsyncSession, project_id: UUID
) -> OrchestratorRunResult:
    """Persist a safe terminal state when cancellation lands between stages."""

    await session.rollback()
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    running_rounds = list(
        (
            await session.scalars(
                select(Round).where(
                    Round.project_id == project.id,
                    Round.status == RoundStatus.RUNNING,
                )
            )
        ).all()
    )
    for round_record in running_rounds:
        round_record.status = RoundStatus.CANCELLED
        round_record.error = "Stopped by user"
        round_record.completed_at = utc_now()
    if project.status == ProjectStatus.STRUCTURING:
        project.status = ProjectStatus.DRAFT
    await session.commit()
    return _result(
        project, [], None, OrchestratorStopReason.USER_CANCELLED
    )


def _require_not_cancelled(project_id: UUID) -> None:
    if workflow_progress.cancellation_requested(project_id):
        raise WorkflowCancellationRequested(str(project_id))


def _record_recovered_failure(
    warnings: list[str],
    events: list[object],
    error: AgentExecutionFailedError,
    stage: str,
    iteration: int,
) -> None:
    message = f"{error.agent} {stage} attempt group {iteration}: {error.last_error or error}"
    warnings.append(message[:1000])
    events.append(
        {
            "agent": error.agent,
            "stage": stage,
            "status": "RECOVERED_FAILURE",
            "output": {
                "error": error.last_error or str(error),
                "attempts": error.attempts,
            },
        }
    )


def _is_output_truncation(error: AgentExecutionFailedError) -> bool:
    return "max_output_tokens" in (error.last_error or "").lower()


async def list_rounds(session: AsyncSession, project_id: UUID) -> Sequence[Round]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    result = await session.scalars(
        select(Round)
        .where(Round.project_id == str(project_id))
        .order_by(Round.round_number.asc())
    )
    return result.all()


async def _require_no_running_round(session: AsyncSession, project_id: str) -> None:
    running_round_id = await session.scalar(
        select(Round.id)
        .where(
            Round.project_id == project_id,
            Round.status == RoundStatus.RUNNING,
        )
        .limit(1)
    )
    if running_round_id is not None:
        raise OrchestratorAlreadyRunningError(project_id)


async def _has_idea_version(session: AsyncSession, project_id: str) -> bool:
    version_id = await session.scalar(
        select(IdeaVersion.id).where(IdeaVersion.project_id == project_id).limit(1)
    )
    return version_id is not None


async def _next_round_number(session: AsyncSession, project_id: str) -> int:
    current_maximum = await session.scalar(
        select(func.max(Round.round_number)).where(Round.project_id == project_id)
    )
    return int(current_maximum or 0) + 1


async def _latest_decision(
    session: AsyncSession, project_id: str
) -> DecisionRecord | None:
    return await session.scalar(
        select(DecisionRecord)
        .where(DecisionRecord.project_id == project_id)
        .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
        .limit(1)
    )


async def _latest_score(
    session: AsyncSession, project_id: str
) -> ProjectScore | None:
    return await session.scalar(
        select(ProjectScore)
        .where(ProjectScore.project_id == project_id)
        .order_by(ProjectScore.created_at.desc(), ProjectScore.id.desc())
        .limit(1)
    )


def adaptive_agent_plan(
    configured: AgentExecutionPlan,
    *,
    previous_score: int | None,
    previous_confidence: float | None,
    enabled: bool,
    score_threshold: int,
    confidence_threshold: float,
) -> AgentExecutionPlan:
    """Treat configured depth as a maximum and earn extra calls from evidence."""

    if not enabled:
        return configured

    def base(value: int) -> int:
        return 0 if value == 0 else 1

    if previous_score is None or previous_confidence is None:
        return AgentExecutionPlan(
            builder=base(configured.builder),
            researcher=base(configured.researcher),
            critic=base(configured.critic),
        )

    low_score = previous_score < score_threshold
    low_confidence = previous_confidence < confidence_threshold
    return AgentExecutionPlan(
        builder=(configured.builder if low_score else base(configured.builder)),
        researcher=(
            configured.researcher
            if low_confidence
            else base(configured.researcher)
        ),
        critic=(
            configured.critic
            if low_score or low_confidence
            else base(configured.critic)
        ),
    )


async def _round_decision(
    session: AsyncSession, round_id: str
) -> DecisionRecord:
    decision = await session.scalar(
        select(DecisionRecord)
        .join(AgentRun, DecisionRecord.agent_run_id == AgentRun.id)
        .where(AgentRun.round_id == round_id)
        .order_by(DecisionRecord.created_at.desc())
        .limit(1)
    )
    if decision is None:
        raise RuntimeError("Judge did not persist a round decision")
    return decision


def _decision_instruction(
    decision: DecisionRecord | None,
    improvement_plan: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if decision is None:
        return (
            {"improvement_plan": improvement_plan}
            if improvement_plan is not None
            else None
        )
    if decision.human_action == HumanReviewAction.MANUAL_PIVOT:
        instruction: dict[str, object] = {
            "decision": DecisionType.PIVOT.value,
            "reason": decision.human_note or decision.reason,
            "critical_blockers": decision.critical_blockers,
            "next_actions": decision.next_actions,
            "human_instruction": decision.human_note,
        }
    elif (
        decision.human_review_status == HumanReviewStatus.OVERRIDDEN
        and decision.human_action == HumanReviewAction.CONTINUE_ANYWAY
    ):
        instruction = {}
    else:
        instruction = {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "critical_blockers": decision.critical_blockers,
            "next_actions": decision.next_actions,
            "human_instruction": decision.human_note,
        }
    if improvement_plan is not None:
        instruction["improvement_plan"] = improvement_plan
    return instruction or None


def _link_previous_decision(
    decision: DecisionRecord | None, resulting_version_id: str
) -> None:
    if (
        decision is not None
        and decision.to_version_id is None
        and decision.decision in {DecisionType.REFINE, DecisionType.PIVOT}
    ):
        decision.to_version_id = resulting_version_id


def _result(
    project: Project,
    rounds: list[RoundRead],
    final_output: JudgeOutput | None,
    stop_reason: OrchestratorStopReason | None,
) -> OrchestratorRunResult:
    if stop_reason is None:
        raise RuntimeError("A stopped orchestration requires a stop reason")
    return OrchestratorRunResult(
        project_id=project.id,
        project_status=project.status,
        rounds=rounds,
        final_decision=final_output.decision if final_output is not None else None,
        final_score=final_output.score if final_output is not None else None,
        final_confidence=(
            final_output.confidence if final_output is not None else None
        ),
        stop_reason=stop_reason,
    )
