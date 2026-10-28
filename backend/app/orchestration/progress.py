import asyncio
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from app.domain.enums import AgentType, WorkflowExecutionStatus
from app.schemas.orchestration import WorkflowProgressRead


class WorkflowProgressStore:
    """Process-local live workflow state for the single-worker desktop API."""

    def __init__(self) -> None:
        self._items: dict[str, WorkflowProgressRead] = {}
        self._tasks: dict[str, asyncio.Task[object]] = {}
        self._lock = RLock()

    def start(self, project_id: UUID, requested_rounds: int) -> bool:
        key = str(project_id)
        now = datetime.now(UTC)
        with self._lock:
            if key in self._items:
                return False
            self._items[key] = WorkflowProgressRead(
                project_id=project_id,
                status=WorkflowExecutionStatus.RUNNING,
                requested_rounds=requested_rounds,
                started_at=now,
                updated_at=now,
            )
        return True

    def bind_task(self, project_id: UUID, task: asyncio.Task[object]) -> bool:
        """Attach the cancellable workflow task to its live progress record."""

        key = str(project_id)
        with self._lock:
            if key not in self._items:
                return False
            self._tasks[key] = task
            return True

    def set_agent(
        self,
        project_id: UUID,
        agent: AgentType,
        *,
        current_round: int | None,
        round_position: int | None,
        agent_iteration: int = 1,
        agent_iterations: int = 1,
        workflow_stage: str | None = None,
    ) -> None:
        key = str(project_id)
        with self._lock:
            current = self._items.get(key)
            if current is None:
                return
            self._items[key] = current.model_copy(
                update={
                    "current_agent": agent,
                    "workflow_stage": workflow_stage,
                    "current_round": current_round,
                    "round_position": round_position,
                    "agent_iteration": agent_iteration,
                    "agent_iterations": agent_iterations,
                    "updated_at": datetime.now(UTC),
                }
            )

    def request_cancel(self, project_id: UUID) -> WorkflowProgressRead | None:
        key = str(project_id)
        with self._lock:
            current = self._items.get(key)
            if current is None:
                return None
            cancelled = current.model_copy(
                update={
                    "status": WorkflowExecutionStatus.CANCELLING,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._items[key] = cancelled
            task = self._tasks.get(key)
            result = cancelled.model_copy(deep=True)
        if task is not None and not task.done():
            task.cancel("Workflow cancelled by user")
        return result

    def cancellation_requested(self, project_id: UUID) -> bool:
        with self._lock:
            current = self._items.get(str(project_id))
            return (
                current is not None
                and current.status == WorkflowExecutionStatus.CANCELLING
            )

    def finish(self, project_id: UUID) -> None:
        with self._lock:
            key = str(project_id)
            self._items.pop(key, None)
            self._tasks.pop(key, None)

    def get(self, project_id: UUID) -> WorkflowProgressRead:
        with self._lock:
            current = self._items.get(str(project_id))
            if current is not None:
                return current.model_copy(deep=True)
        return WorkflowProgressRead(
            project_id=project_id,
            status=WorkflowExecutionStatus.IDLE,
        )


workflow_progress = WorkflowProgressStore()
