from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DecisionRecord, Project, utc_now
from app.domain.enums import (
    DecisionType,
    HumanReviewAction,
    HumanReviewStatus,
    ProjectStatus,
)
from app.schemas.human_review import HumanReviewRequest
from app.services.errors import (
    DecisionNotFoundError,
    HumanReviewNotPendingError,
    PendingHumanReviewError,
    ProjectNotFoundError,
)


REVIEW_REQUIRED_DECISIONS = frozenset(
    {DecisionType.APPROVE, DecisionType.DISCARD, DecisionType.PIVOT}
)


def review_status_for(decision: DecisionType) -> HumanReviewStatus:
    if decision in REVIEW_REQUIRED_DECISIONS:
        return HumanReviewStatus.PENDING
    return HumanReviewStatus.NOT_REQUIRED


async def review_decision(
    session: AsyncSession,
    project_id: UUID,
    decision_id: UUID,
    payload: HumanReviewRequest,
) -> DecisionRecord:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    decision = await session.get(DecisionRecord, str(decision_id))
    if decision is None or decision.project_id != project.id:
        raise DecisionNotFoundError(str(decision_id))
    if decision.human_review_status != HumanReviewStatus.PENDING:
        raise HumanReviewNotPendingError(decision.id)

    if payload.action == HumanReviewAction.ACCEPT_RECOMMENDATION:
        decision.human_review_status = HumanReviewStatus.ACCEPTED
        project.status = _accepted_status(decision.decision)
    elif payload.action == HumanReviewAction.MANUAL_PIVOT:
        decision.human_review_status = HumanReviewStatus.OVERRIDDEN
        project.status = ProjectStatus.PIVOTING
    else:
        decision.human_review_status = HumanReviewStatus.OVERRIDDEN
        project.status = ProjectStatus.DEBATING

    decision.human_action = payload.action
    decision.human_note = payload.note
    decision.reviewed_at = utc_now()
    await session.commit()
    await session.refresh(decision)
    return decision


async def require_no_pending_review(session: AsyncSession, project_id: str) -> None:
    pending_id = await session.scalar(
        select(DecisionRecord.id)
        .where(
            DecisionRecord.project_id == project_id,
            DecisionRecord.human_review_status == HumanReviewStatus.PENDING,
        )
        .limit(1)
    )
    if pending_id is not None:
        raise PendingHumanReviewError(pending_id)


def _accepted_status(decision: DecisionType) -> ProjectStatus:
    if decision == DecisionType.APPROVE:
        return ProjectStatus.APPROVED
    if decision == DecisionType.DISCARD:
        return ProjectStatus.DISCARDED
    if decision == DecisionType.PIVOT:
        return ProjectStatus.PIVOTING
    raise HumanReviewNotPendingError(
        f"Decision {decision.value} does not require human review"
    )
