from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DecisionRecord, Evidence, Experiment
from app.domain.enums import ExperimentReassessmentStatus, ExperimentStatus
from app.llm.base import LLMProvider
from app.services import judging as judging_service
from app.services.errors import (
    BudgetLimitReachedError,
    ExperimentNotFoundError,
    ExperimentValidationError,
)


async def reassess_completed_experiment(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
    provider: LLMProvider,
) -> Experiment:
    experiment = await _require_completed_experiment(
        session, project_id, experiment_id
    )
    if experiment.reassessment_status != ExperimentReassessmentStatus.PENDING:
        raise ExperimentValidationError(
            "Experiment must be prepared before reassessment"
        )

    try:
        evidence = (
            await session.get(Evidence, experiment.evidence_id)
            if experiment.evidence_id
            else None
        )
        output = await judging_service.run_judge(
            session,
            project_id,
            provider,
            user_context=(
                "Focused reassessment after a completed experiment. Re-evaluate only "
                "criteria supported by the linked experimental evidence and its quality. "
                "A negative high-quality result may lower the score while increasing "
                "confidence; an inconclusive or weak result must not automatically change "
                "either measure."
            ),
            accumulated_context={
                "trigger": "EXPERIMENT_COMPLETED",
                "experiment_id": str(experiment_id),
                "evidence_id": evidence.code if evidence else None,
                "evidence_quality": experiment.evidence_quality,
                "affected_criteria": experiment.affected_criteria,
            },
        )
        decision = await session.scalar(
            select(DecisionRecord)
            .where(DecisionRecord.project_id == str(project_id))
            .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
            .limit(1)
        )
        experiment = await _require_completed_experiment(
            session, project_id, experiment_id
        )
        experiment.reassessment_status = ExperimentReassessmentStatus.COMPLETED
        experiment.reassessed_score = output.score
        experiment.reassessed_confidence = output.confidence
        experiment.reassessment_score_id = decision.score_id if decision else None
        experiment.reassessment_decision_id = decision.id if decision else None
        experiment.reassessment_error = None
        await session.commit()
        await session.refresh(experiment)
        return experiment
    except BudgetLimitReachedError as exc:
        await session.rollback()
        return await _mark_failed(
            session,
            project_id,
            experiment_id,
            ExperimentReassessmentStatus.SKIPPED_BUDGET,
            str(exc) or "Project AI budget is exhausted",
        )
    except Exception as exc:
        await session.rollback()
        return await _mark_failed(
            session,
            project_id,
            experiment_id,
            ExperimentReassessmentStatus.FAILED,
            f"{type(exc).__name__}: {exc}",
        )


async def _mark_failed(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
    status: ExperimentReassessmentStatus,
    error: str,
) -> Experiment:
    experiment = await _require_completed_experiment(
        session, project_id, experiment_id
    )
    experiment.reassessment_status = status
    experiment.reassessment_error = error[:2000]
    await session.commit()
    await session.refresh(experiment)
    return experiment


async def _require_completed_experiment(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
) -> Experiment:
    experiment = await session.get(Experiment, str(experiment_id))
    if experiment is None or experiment.project_id != str(project_id):
        raise ExperimentNotFoundError(str(experiment_id))
    if experiment.status != ExperimentStatus.COMPLETED:
        raise ExperimentValidationError(
            "Only a completed experiment can be reassessed"
        )
    return experiment
