from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Round, WorkflowExecution
from app.domain.enums import RoundStatus, WorkflowExecutionStatus
from app.schemas.orchestration import WorkflowProgressRead


STALE_AFTER = timedelta(seconds=30)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_stale(row: WorkflowExecution, now: datetime) -> bool:
    heartbeat = _utc(row.heartbeat_at or row.updated_at)
    return bool(
        row.status != WorkflowExecutionStatus.IDLE
        and heartbeat is not None
        and now - heartbeat > STALE_AFTER
    )


def _reset(row: WorkflowExecution, now: datetime) -> None:
    row.status = WorkflowExecutionStatus.IDLE
    row.owner_id = None
    row.cancellation_requested = False
    row.current_agent = None
    row.workflow_stage = None
    row.current_round = None
    row.round_position = None
    row.requested_rounds = None
    row.agent_iteration = None
    row.agent_iterations = None
    row.updated_at = now
    row.heartbeat_at = None
    row.completed_at = now


async def _cancel_orphaned_rounds(
    session: AsyncSession, project_id: str, now: datetime
) -> None:
    rounds = list(
        (
            await session.scalars(
                select(Round).where(
                    Round.project_id == project_id,
                    Round.status == RoundStatus.RUNNING,
                )
            )
        ).all()
    )
    for round_record in rounds:
        round_record.status = RoundStatus.CANCELLED
        round_record.error = "Execução interrompida por reinício do servidor"
        round_record.completed_at = now


async def claim(
    session: AsyncSession,
    project_id: UUID,
    *,
    owner_id: str,
    requested_rounds: int,
) -> bool:
    now = datetime.now(UTC)
    row = await session.get(WorkflowExecution, str(project_id))
    if row is None:
        try:
            async with session.begin_nested():
                session.add(WorkflowExecution(project_id=str(project_id)))
                await session.flush()
        except IntegrityError:
            pass
    elif _is_stale(row, now):
        _reset(row, now)
        await _cancel_orphaned_rounds(session, str(project_id), now)
        await session.flush()
    stale_before = now - STALE_AFTER
    claimed = await session.execute(
        update(WorkflowExecution)
        .where(
            WorkflowExecution.project_id == str(project_id),
            or_(
                WorkflowExecution.status == WorkflowExecutionStatus.IDLE,
                and_(
                    WorkflowExecution.status != WorkflowExecutionStatus.IDLE,
                    func.coalesce(
                        WorkflowExecution.heartbeat_at, WorkflowExecution.updated_at
                    )
                    < stale_before,
                ),
            ),
        )
        .values(
            status=WorkflowExecutionStatus.RUNNING,
            owner_id=owner_id,
            cancellation_requested=False,
            current_agent=None,
            workflow_stage=None,
            current_round=None,
            round_position=None,
            requested_rounds=requested_rounds,
            agent_iteration=None,
            agent_iterations=None,
            started_at=now,
            updated_at=now,
            heartbeat_at=now,
            completed_at=None,
        )
    )
    if claimed.rowcount != 1:
        await session.rollback()
        return False
    await session.commit()
    return True


async def sync_progress(
    session: AsyncSession,
    progress: WorkflowProgressRead,
    *,
    owner_id: str,
) -> bool:
    row = await session.get(WorkflowExecution, str(progress.project_id))
    if row is None or row.owner_id != owner_id:
        return False
    now = datetime.now(UTC)
    if row.cancellation_requested:
        row.status = WorkflowExecutionStatus.CANCELLING
    else:
        row.status = progress.status
    row.current_agent = progress.current_agent
    row.workflow_stage = progress.workflow_stage
    row.current_round = progress.current_round
    row.round_position = progress.round_position
    row.requested_rounds = progress.requested_rounds
    row.agent_iteration = progress.agent_iteration
    row.agent_iterations = progress.agent_iterations
    row.updated_at = now
    row.heartbeat_at = now
    await session.commit()
    return row.cancellation_requested


async def request_cancel(
    session: AsyncSession, project_id: UUID
) -> WorkflowProgressRead | None:
    row = await session.scalar(
        select(WorkflowExecution)
        .where(WorkflowExecution.project_id == str(project_id))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None or row.status == WorkflowExecutionStatus.IDLE:
        return None
    if _is_stale(row, now):
        _reset(row, now)
        await _cancel_orphaned_rounds(session, str(project_id), now)
        await session.commit()
        return None
    row.status = WorkflowExecutionStatus.CANCELLING
    row.cancellation_requested = True
    row.updated_at = now
    await session.commit()
    return to_read(row)


async def get_progress(
    session: AsyncSession, project_id: UUID
) -> WorkflowProgressRead:
    row = await session.get(WorkflowExecution, str(project_id))
    now = datetime.now(UTC)
    if row is None:
        return WorkflowProgressRead(
            project_id=project_id, status=WorkflowExecutionStatus.IDLE
        )
    if _is_stale(row, now):
        _reset(row, now)
        await _cancel_orphaned_rounds(session, str(project_id), now)
        await session.commit()
    return to_read(row)


async def finish(
    session: AsyncSession, project_id: UUID, *, owner_id: str
) -> None:
    row = await session.get(WorkflowExecution, str(project_id))
    if row is None or row.owner_id != owner_id:
        return
    _reset(row, datetime.now(UTC))
    await session.commit()


def to_read(row: WorkflowExecution) -> WorkflowProgressRead:
    return WorkflowProgressRead(
        project_id=UUID(row.project_id),
        status=row.status,
        current_agent=row.current_agent,
        workflow_stage=row.workflow_stage,
        current_round=row.current_round,
        round_position=row.round_position,
        requested_rounds=row.requested_rounds,
        agent_iteration=row.agent_iteration,
        agent_iterations=row.agent_iterations,
        started_at=row.started_at,
        updated_at=row.updated_at,
    )
