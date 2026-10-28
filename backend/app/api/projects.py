import asyncio
from contextlib import suppress
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.database.session import get_db_session
from app.domain.enums import AgentType, ExperimentReassessmentStatus
from app.llm.dependencies import get_llm_router
from app.llm.providers.http import ProviderConfigurationError, ProviderRequestError
from app.llm.router import LLMRouter
from app.orchestration import orchestrator as orchestrator_service
from app.orchestration.progress import workflow_progress
from app.orchestration.rules import require_non_terminal_project
from app.schemas.evaluation import BuilderOutput, CriticismRead, CriticOutput
from app.schemas.discovery import DiscoveryHandoffRead
from app.schemas.experiments import ExperimentCreate, ExperimentRead, ExperimentUpdate
from app.schemas.human_review import HumanReviewRequest
from app.schemas.idea import IdeaVersionRead
from app.schemas.judgment import DecisionRead, JudgeOutput, ScoreRead
from app.schemas.judge_chat import (
    JudgeChatTurnCreate,
    JudgeChatTurnRead,
    JudgeVoiceSessionRead,
)
from app.schemas.improvement import ImprovementPlanRead
from app.schemas.knowledge import (
    EvidenceCreate,
    EvidenceRead,
    HypothesisCreate,
    HypothesisRead,
    HypothesisUpdate,
)
from app.schemas.orchestration import (
    OrchestratorRunRequest,
    OrchestratorRunResult,
    RoundRead,
    WorkflowProgressRead,
)
from app.schemas.project import (
    ProjectAgentPlanUpdate,
    ProjectBudgetUpdate,
    ProjectCreate,
    ProjectNextRoundContextUpdate,
    ProjectRead,
)
from app.schemas.profiles import ProjectProfileUpdate
from app.schemas.research import ResearcherOutput
from app.schemas.timeline import TimelineItemRead
from app.services import evaluation as evaluation_service
from app.services import discovery as discovery_service
from app.services import experiments as experiment_service
from app.services import experiment_reassessment as experiment_reassessment_service
from app.services import human_review as human_review_service
from app.services import knowledge as knowledge_service
from app.services import projects as project_service
from app.services import profiles as profile_service
from app.services import research as research_service
from app.services import judging as judging_service
from app.services import judge_chat as judge_chat_service
from app.services import judge_voice as judge_voice_service
from app.services import improvements as improvement_service
from app.services import structuring as structuring_service
from app.services import timeline as timeline_service
from app.services import workflow_executions as workflow_execution_service
from app.services.budget import require_budget_available
from app.services.errors import (
    AgentExecutionFailedError,
    AgentProfileNotFoundError,
    BudgetLimitReachedError,
    HypothesisAlreadyExistsError,
    HypothesisNotFoundError,
    DecisionNotFoundError,
    ExperimentNotFoundError,
    ExperimentValidationError,
    HumanReviewNotPendingError,
    OrchestratorAlreadyRunningError,
    ProjectAlreadyStructuredError,
    ProjectNotFoundError,
    ProjectNotStructuredError,
    ProjectNotEvaluatedError,
    ProjectTerminalError,
    PendingExperimentError,
    PendingHumanReviewError,
    RoundLimitExceededError,
)


router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
ModelRouter = Annotated[LLMRouter, Depends(get_llm_router)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def _workflow_watchdog(
    project_id: UUID,
    owner_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Bridge the durable cancel flag to the HTTP task owned by this worker."""

    while True:
        local = workflow_progress.get(project_id)
        async with session_factory() as watcher_session:
            should_cancel = await workflow_execution_service.sync_progress(
                watcher_session, local, owner_id=owner_id
            )
        if should_cancel:
            workflow_progress.request_cancel(project_id)
        await asyncio.sleep(0.35)


async def _start_workflow_tracking(
    session: AsyncSession, project_id: UUID, requested_rounds: int
) -> tuple[str, asyncio.Task[None] | None]:
    owner_id = str(uuid4())
    claimed = await workflow_execution_service.claim(
        session,
        project_id,
        owner_id=owner_id,
        requested_rounds=requested_rounds,
    )
    if not claimed:
        raise OrchestratorAlreadyRunningError(str(project_id))
    if not workflow_progress.start(project_id, requested_rounds):
        await workflow_execution_service.finish(
            session, project_id, owner_id=owner_id
        )
        raise OrchestratorAlreadyRunningError(str(project_id))
    if session.bind is None:
        raise RuntimeError("Workflow persistence requires a bound database session")
    # In-memory SQLite tests share one physical connection; a concurrent
    # heartbeat transaction would interfere with the request transaction.
    if (
        session.bind.url.get_backend_name() == "sqlite"
        and not session.bind.url.database
    ):
        return owner_id, None
    watcher_factory = async_sessionmaker(session.bind, expire_on_commit=False)
    return owner_id, asyncio.create_task(
        _workflow_watchdog(project_id, owner_id, watcher_factory)
    )


async def _finish_workflow_tracking(
    session: AsyncSession,
    project_id: UUID,
    owner_id: str | None,
    watchdog: asyncio.Task[None] | None,
) -> None:
    if watchdog is not None:
        watchdog.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog
    workflow_progress.finish(project_id)
    if owner_id is not None:
        await workflow_execution_service.finish(session, project_id, owner_id=owner_id)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: DatabaseSession) -> ProjectRead:
    try:
        return await project_service.create_project(session, payload)
    except AgentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ProjectRead]:
    return list(await project_service.list_projects(session, offset=offset, limit=limit))


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID, session: DatabaseSession) -> ProjectRead:
    project = await project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


@router.get(
    "/{project_id}/discovery-handoff",
    response_model=DiscoveryHandoffRead | None,
)
async def get_project_discovery_handoff(
    project_id: UUID, session: DatabaseSession
) -> DiscoveryHandoffRead | None:
    project = await project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await discovery_service.get_project_handoff(session, project_id)


@router.patch("/{project_id}/budget", response_model=ProjectRead)
async def update_project_budget(
    project_id: UUID, payload: ProjectBudgetUpdate, session: DatabaseSession
) -> ProjectRead:
    project = await project_service.update_project_budget(session, project_id, payload)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


@router.patch("/{project_id}/agent-profile", response_model=ProjectRead)
async def update_project_profile(
    project_id: UUID, payload: ProjectProfileUpdate, session: DatabaseSession
) -> ProjectRead:
    try:
        project = await project_service.update_project_profile(
            session, project_id, payload
        )
    except AgentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}/agent-plan", response_model=ProjectRead)
async def update_project_agent_plan(
    project_id: UUID, payload: ProjectAgentPlanUpdate, session: DatabaseSession
) -> ProjectRead:
    project = await project_service.update_project_agent_plan(
        session, project_id, payload
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}/next-round-context", response_model=ProjectRead)
async def update_next_round_context(
    project_id: UUID,
    payload: ProjectNextRoundContextUpdate,
    session: DatabaseSession,
) -> ProjectRead:
    project = await project_service.update_next_round_context(
        session, project_id, payload
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post(
    "/{project_id}/structure",
    response_model=IdeaVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def structure_project(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> IdeaVersionRead:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await structuring_service.structure_project(
            session,
            project_id,
            llm_router.provider_for(AgentType.STRUCTURER),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except ProjectAlreadyStructuredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project already has an initial idea version",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Idea structuring failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.get("/{project_id}/versions", response_model=list[IdeaVersionRead])
async def list_idea_versions(
    project_id: UUID, session: DatabaseSession
) -> list[IdeaVersionRead]:
    try:
        return list(await structuring_service.list_idea_versions(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.post("/{project_id}/builder", response_model=BuilderOutput)
async def run_builder(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> BuilderOutput:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await evaluation_service.run_builder(
            session, project_id, llm_router.provider_for(AgentType.BUILDER)
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project must be structured before running Builder",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Builder failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.post("/{project_id}/critic", response_model=CriticOutput)
async def run_critic(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> CriticOutput:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await evaluation_service.run_critic(
            session, project_id, llm_router.provider_for(AgentType.CRITIC)
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project must be structured before running Critic",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Critic failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.get("/{project_id}/criticisms", response_model=list[CriticismRead])
async def list_criticisms(
    project_id: UUID, session: DatabaseSession
) -> list[CriticismRead]:
    try:
        return list(await evaluation_service.list_criticisms(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.post("/{project_id}/researcher", response_model=ResearcherOutput)
async def run_researcher(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> ResearcherOutput:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await research_service.run_researcher(
            session,
            project_id,
            llm_router.provider_for(AgentType.RESEARCHER),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project must be structured before running Researcher",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Researcher failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.post("/{project_id}/judge", response_model=JudgeOutput)
async def run_judge(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> JudgeOutput:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await judging_service.run_judge(
            session, project_id, llm_router.provider_for(AgentType.JUDGE)
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project must be structured before running Judge",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Judge failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.get("/{project_id}/scores", response_model=list[ScoreRead])
async def list_scores(project_id: UUID, session: DatabaseSession) -> list[ScoreRead]:
    try:
        return list(await judging_service.list_scores(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.get("/{project_id}/decisions", response_model=list[DecisionRead])
async def list_decisions(
    project_id: UUID, session: DatabaseSession
) -> list[DecisionRead]:
    try:
        return await judging_service.list_decisions(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.post("/{project_id}/improver", response_model=ImprovementPlanRead)
async def run_improver(
    project_id: UUID, session: DatabaseSession, llm_router: ModelRouter
) -> ImprovementPlanRead:
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await improvement_service.run_improver(
            session, project_id, llm_router.provider_for(AgentType.IMPROVER)
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=409, detail="Project must be structured before running Improver"
        ) from exc
    except ProjectNotEvaluatedError as exc:
        raise HTTPException(
            status_code=409, detail="Run Judge before running Improver"
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail="Improver failed after the configured attempts",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.get("/{project_id}/improvement-plans", response_model=list[ImprovementPlanRead])
async def list_improvement_plans(
    project_id: UUID, session: DatabaseSession
) -> list[ImprovementPlanRead]:
    try:
        return list(await improvement_service.list_improvement_plans(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/{project_id}/judge-chat", response_model=list[JudgeChatTurnRead])
async def list_judge_chat_turns(
    project_id: UUID, session: DatabaseSession
) -> list[JudgeChatTurnRead]:
    try:
        return list(await judge_chat_service.list_turns(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/judge-voice/session", response_model=JudgeVoiceSessionRead)
async def create_judge_voice_session(
    project_id: UUID,
    session: DatabaseSession,
    settings: AppSettings,
) -> JudgeVoiceSessionRead:
    try:
        project = await project_service.get_project(session, project_id)
        if project is None:
            raise ProjectNotFoundError(str(project_id))
        require_non_terminal_project(project.status)
        await human_review_service.require_no_pending_review(session, project.id)
        await experiment_service.require_no_open_experiments(session, project.id)
        require_budget_available(project)
        return await judge_voice_service.create_session(
            settings,
            project_id,
            project_name=project.name,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectTerminalError as exc:
        raise HTTPException(
            status_code=409,
            detail="A terminal project cannot start a Judge voice session",
        ) from exc
    except PendingHumanReviewError as exc:
        raise HTTPException(
            status_code=409,
            detail="A human decision review is required before voice chat",
        ) from exc
    except PendingExperimentError as exc:
        raise HTTPException(
            status_code=409,
            detail="Complete or cancel the open experiment before voice chat",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível iniciar a voz natural na OpenAI.",
        ) from exc


@router.post("/{project_id}/judge-chat", response_model=JudgeChatTurnRead)
async def run_judge_chat_turn(
    project_id: UUID,
    payload: JudgeChatTurnCreate,
    session: DatabaseSession,
    llm_router: ModelRouter,
) -> JudgeChatTurnRead:
    turn_id: str | None = None
    progress_owner: str | None = None
    progress_watchdog: asyncio.Task[None] | None = None
    try:
        project = await project_service.get_project(session, project_id)
        if project is None:
            raise ProjectNotFoundError(str(project_id))
        require_non_terminal_project(project.status)
        await human_review_service.require_no_pending_review(session, project.id)
        await experiment_service.require_no_open_experiments(session, project.id)
        require_budget_available(project)
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        progress_owner, progress_watchdog = await _start_workflow_tracking(
            session, project_id, 1
        )
        previous_decision_id = await judge_chat_service.latest_decision_id(
            session, project_id
        )
        turn = await judge_chat_service.create_running_turn(
            session,
            project,
            message=payload.message,
            input_mode=payload.input_mode,
        )
        turn_id = turn.id
        run_task = asyncio.create_task(
            orchestrator_service.run_project(
                session,
                project_id,
                llm_router,
                max_rounds=1,
            )
        )
        workflow_progress.bind_task(project_id, run_task)
        try:
            result = await run_task
        except asyncio.CancelledError:
            result = await orchestrator_service.cancelled_run_result(
                session, project_id
            )
        return await judge_chat_service.complete_turn(
            session,
            turn.id,
            project_id,
            previous_decision_id=previous_decision_id,
            stop_reason=result.stop_reason,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except OrchestratorAlreadyRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail="A workflow run is already active for this project",
        ) from exc
    except ProjectTerminalError as exc:
        raise HTTPException(
            status_code=409,
            detail="A terminal project cannot start another workflow run",
        ) from exc
    except PendingHumanReviewError as exc:
        raise HTTPException(
            status_code=409,
            detail="A human decision review is required before another run",
        ) from exc
    except PendingExperimentError as exc:
        raise HTTPException(
            status_code=409,
            detail="Complete or cancel the open experiment before another run",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Workflow stopped at a critical stage: {exc}",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc
    finally:
        if turn_id is not None:
            # Persist the failed conversation without hiding the original API error.
            # Completed turns are left untouched by this guard.
            try:
                turns = await judge_chat_service.list_turns(session, project_id)
                current = next((item for item in turns if str(item.id) == turn_id), None)
                if current is not None and current.status == "RUNNING":
                    await judge_chat_service.fail_turn(
                        session, turn_id, error="Workflow did not reach a new Judge decision"
                    )
            except Exception:
                await session.rollback()
        if progress_owner is not None:
            await _finish_workflow_tracking(
                session, project_id, progress_owner, progress_watchdog
            )


@router.post("/{project_id}/run", response_model=OrchestratorRunResult)
async def run_project_workflow(
    project_id: UUID,
    session: DatabaseSession,
    llm_router: ModelRouter,
    payload: OrchestratorRunRequest = Body(default=OrchestratorRunRequest()),
) -> OrchestratorRunResult:
    progress_owner: str | None = None
    progress_watchdog: asyncio.Task[None] | None = None
    try:
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        progress_owner, progress_watchdog = await _start_workflow_tracking(
            session, project_id, payload.max_rounds
        )
        try:
            run_task = asyncio.create_task(
                orchestrator_service.run_project(
                    session,
                    project_id,
                    llm_router,
                    max_rounds=payload.max_rounds,
                )
            )
            workflow_progress.bind_task(project_id, run_task)
            try:
                return await run_task
            except asyncio.CancelledError:
                return await orchestrator_service.cancelled_run_result(
                    session, project_id
                )
        finally:
            await _finish_workflow_tracking(
                session, project_id, progress_owner, progress_watchdog
            )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except RoundLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except OrchestratorAlreadyRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workflow run is already active for this project",
        ) from exc
    except ProjectTerminalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A terminal project cannot start another workflow run",
        ) from exc
    except PendingHumanReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A human decision review is required before another run",
        ) from exc
    except PendingExperimentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Complete or cancel the open experiment before another run",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Workflow stopped at a critical stage: {exc}",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise _budget_exhausted_http_error() from exc


@router.get("/{project_id}/run-status", response_model=WorkflowProgressRead)
async def workflow_run_status(
    project_id: UUID, session: DatabaseSession
) -> WorkflowProgressRead:
    if await project_service.get_project(session, project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    local = workflow_progress.get(project_id)
    if local.status.value != "IDLE":
        return local
    return await workflow_execution_service.get_progress(session, project_id)


@router.post("/{project_id}/run-cancel", response_model=WorkflowProgressRead)
async def cancel_workflow_run(
    project_id: UUID, session: DatabaseSession
) -> WorkflowProgressRead:
    if await project_service.get_project(session, project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    durable = await workflow_execution_service.request_cancel(session, project_id)
    local = workflow_progress.request_cancel(project_id)
    if durable is None and local is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active workflow run to stop",
        )
    return local or durable


@router.get("/{project_id}/rounds", response_model=list[RoundRead])
async def list_project_rounds(
    project_id: UUID, session: DatabaseSession
) -> list[RoundRead]:
    try:
        return list(await orchestrator_service.list_rounds(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.post(
    "/{project_id}/decisions/{decision_id}/review", response_model=ProjectRead
)
async def review_project_decision(
    project_id: UUID,
    decision_id: UUID,
    payload: HumanReviewRequest,
    session: DatabaseSession,
) -> ProjectRead:
    try:
        await human_review_service.review_decision(
            session, project_id, decision_id, payload
        )
        project = await project_service.get_project(session, project_id)
        if project is None:
            raise ProjectNotFoundError(str(project_id))
        return project
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Decision not found") from exc
    except HumanReviewNotPendingError as exc:
        raise HTTPException(
            status_code=409, detail="Decision is not awaiting human review"
        ) from exc


@router.post(
    "/{project_id}/experiments",
    response_model=ExperimentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_experiment(
    project_id: UUID, payload: ExperimentCreate, session: DatabaseSession
) -> ExperimentRead:
    try:
        return await experiment_service.create_experiment(session, project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except HypothesisNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Hypothesis not found") from exc


@router.get("/{project_id}/experiments", response_model=list[ExperimentRead])
async def list_experiments(
    project_id: UUID, session: DatabaseSession
) -> list[ExperimentRead]:
    try:
        return list(await experiment_service.list_experiments(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.patch(
    "/{project_id}/experiments/{experiment_id}", response_model=ExperimentRead
)
async def update_experiment(
    project_id: UUID,
    experiment_id: UUID,
    payload: ExperimentUpdate,
    session: DatabaseSession,
) -> ExperimentRead:
    try:
        return await experiment_service.update_experiment(
            session, project_id, experiment_id, payload
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{project_id}/experiments/{experiment_id}/reassess",
    response_model=ExperimentRead,
)
async def reassess_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: DatabaseSession,
    llm_router: ModelRouter,
) -> ExperimentRead:
    try:
        await experiment_service.prepare_experiment_reassessment(
            session, project_id, experiment_id
        )
        llm_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await experiment_reassessment_service.reassess_completed_experiment(
            session,
            project_id,
            experiment_id,
            llm_router.provider_for(AgentType.JUDGE),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/timeline", response_model=list[TimelineItemRead])
async def list_project_timeline(
    project_id: UUID, session: DatabaseSession
) -> list[TimelineItemRead]:
    try:
        return await timeline_service.list_timeline(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.post(
    "/{project_id}/hypotheses",
    response_model=HypothesisRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_hypothesis(
    project_id: UUID, payload: HypothesisCreate, session: DatabaseSession
) -> HypothesisRead:
    try:
        return await knowledge_service.create_hypothesis(session, project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc
    except HypothesisAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An equivalent hypothesis already exists",
        ) from exc


@router.get("/{project_id}/hypotheses", response_model=list[HypothesisRead])
async def list_hypotheses(
    project_id: UUID, session: DatabaseSession
) -> list[HypothesisRead]:
    try:
        return await knowledge_service.list_hypotheses(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.patch(
    "/{project_id}/hypotheses/{hypothesis_id}", response_model=HypothesisRead
)
async def update_hypothesis(
    project_id: UUID,
    hypothesis_id: str,
    payload: HypothesisUpdate,
    session: DatabaseSession,
) -> HypothesisRead:
    try:
        return await knowledge_service.update_hypothesis(
            session, project_id, hypothesis_id, payload
        )
    except (ProjectNotFoundError, HypothesisNotFoundError) as exc:
        detail = (
            "Project not found"
            if isinstance(exc, ProjectNotFoundError)
            else "Hypothesis not found in this project"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=detail
        ) from exc


@router.post(
    "/{project_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence(
    project_id: UUID, payload: EvidenceCreate, session: DatabaseSession
) -> EvidenceRead:
    try:
        return await knowledge_service.create_evidence(session, project_id, payload)
    except (ProjectNotFoundError, HypothesisNotFoundError) as exc:
        detail = (
            "Project not found"
            if isinstance(exc, ProjectNotFoundError)
            else "Hypothesis not found in this project"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=detail
        ) from exc


@router.get("/{project_id}/evidence", response_model=list[EvidenceRead])
async def list_evidence(
    project_id: UUID, session: DatabaseSession
) -> list[EvidenceRead]:
    try:
        return await knowledge_service.list_evidence(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


def _budget_exhausted_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Project AI budget is exhausted",
    )
