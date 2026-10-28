from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DecisionRecord,
    Evidence,
    Experiment,
    Hypothesis,
    IdeaVersion,
    Project,
    ProjectScore,
    utc_now,
)
from app.domain.enums import (
    EpistemicClassification,
    EvidenceDirection,
    EvidenceOrigin,
    ExperimentOutcome,
    ExperimentReassessmentStatus,
    ExperimentStatus,
    HypothesisOrigin,
    HypothesisStatus,
    ScoreCriterion,
)
from app.schemas.experiments import ExperimentCreate, ExperimentUpdate
from app.services.errors import (
    ExperimentNotFoundError,
    ExperimentValidationError,
    HypothesisNotFoundError,
    PendingExperimentError,
    ProjectNotFoundError,
)


OPEN_EXPERIMENT_STATUSES = frozenset(
    {ExperimentStatus.PLANNED, ExperimentStatus.RUNNING}
)


async def create_experiment(
    session: AsyncSession, project_id: UUID, payload: ExperimentCreate
) -> Experiment:
    project = await _require_project(session, project_id)
    if payload.hypothesis_id is not None:
        await _require_hypothesis(session, project.id, str(payload.hypothesis_id))
    experiment = Experiment(
        project_id=project.id,
        hypothesis_id=str(payload.hypothesis_id) if payload.hypothesis_id else None,
        experiment_type=payload.experiment_type,
        description=payload.description,
        success_metric=payload.success_metric,
        success_threshold=payload.success_threshold,
        estimated_cost=payload.estimated_cost,
    )
    session.add(experiment)
    await session.commit()
    await session.refresh(experiment)
    return experiment


async def ensure_experiment_for_decision(
    session: AsyncSession, decision: DecisionRecord
) -> Experiment:
    existing = await session.scalar(
        select(Experiment).where(Experiment.decision_id == decision.id).limit(1)
    )
    if existing is not None:
        return existing
    hypothesis_id = await _highest_priority_hypothesis_id(
        session, decision.project_id
    )
    description = (
        decision.next_actions[0]
        if decision.next_actions
        else f"Validate the decision: {decision.reason}"
    )
    experiment = Experiment(
        project_id=decision.project_id,
        decision_id=decision.id,
        hypothesis_id=hypothesis_id,
        experiment_type="VALIDATION_TEST",
        description=description,
        success_metric=None,
        success_threshold=None,
    )
    session.add(experiment)
    await session.flush()
    return experiment


async def list_experiments(
    session: AsyncSession, project_id: UUID
) -> Sequence[Experiment]:
    await _require_project(session, project_id)
    result = await session.scalars(
        select(Experiment)
        .where(Experiment.project_id == str(project_id))
        .order_by(Experiment.created_at.asc(), Experiment.id.asc())
    )
    return result.all()


async def update_experiment(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
    payload: ExperimentUpdate,
) -> Experiment:
    project = await _require_project(session, project_id)
    experiment = await session.get(Experiment, str(experiment_id))
    if experiment is None or experiment.project_id != project.id:
        raise ExperimentNotFoundError(str(experiment_id))

    changes = payload.model_dump(exclude_unset=True)
    target_status = changes.get("status", experiment.status)
    if target_status == ExperimentStatus.COMPLETED:
        metric = changes.get("success_metric", experiment.success_metric)
        threshold = changes.get("success_threshold", experiment.success_threshold)
        outcome = changes.get("outcome", experiment.outcome)
        result_summary = changes.get("result_summary", experiment.result_summary)
        if not metric or not threshold or outcome is None or not result_summary:
            raise ExperimentValidationError(
                "Para concluir o experimento, preencha a métrica, o limite de sucesso, "
                "o resultado observado e selecione sucesso, falha ou inconclusivo"
            )
    if experiment.status in {ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED}:
        if target_status != experiment.status:
            raise ExperimentValidationError("A closed experiment cannot be reopened")

    is_new_completion = (
        experiment.status != ExperimentStatus.COMPLETED
        and target_status == ExperimentStatus.COMPLETED
    )
    for field, value in changes.items():
        setattr(experiment, field, value)
    if target_status == ExperimentStatus.COMPLETED and experiment.completed_at is None:
        experiment.completed_at = utc_now()
    if is_new_completion:
        await _prepare_completion_traceability(session, project, experiment)
    await session.commit()
    await session.refresh(experiment)
    return experiment


async def prepare_experiment_reassessment(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
) -> Experiment:
    project = await _require_project(session, project_id)
    experiment = await session.get(Experiment, str(experiment_id))
    if experiment is None or experiment.project_id != project.id:
        raise ExperimentNotFoundError(str(experiment_id))
    if experiment.status != ExperimentStatus.COMPLETED:
        raise ExperimentValidationError(
            "Only a completed experiment can be reassessed"
        )
    await _prepare_completion_traceability(session, project, experiment)
    await session.commit()
    await session.refresh(experiment)
    return experiment


async def require_no_open_experiments(
    session: AsyncSession, project_id: str
) -> None:
    experiment_id = await session.scalar(
        select(Experiment.id)
        .where(
            Experiment.project_id == project_id,
            Experiment.status.in_(OPEN_EXPERIMENT_STATUSES),
        )
        .limit(1)
    )
    if experiment_id is not None:
        raise PendingExperimentError(experiment_id)


async def experiment_context(
    session: AsyncSession, project_id: str
) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(Experiment, Evidence.sequence)
        .outerjoin(Evidence, Experiment.evidence_id == Evidence.id)
        .where(Experiment.project_id == project_id)
        .order_by(Experiment.created_at.asc(), Experiment.id.asc())
        )
    ).all()
    return [
        {
            "id": item.id,
            "hypothesis_id": item.hypothesis_id,
            "experiment_type": item.experiment_type,
            "description": item.description,
            "success_metric": item.success_metric,
            "success_threshold": item.success_threshold,
            "status": item.status.value,
            "outcome": item.outcome.value if item.outcome else None,
            "result_summary": item.result_summary,
            "observed_value": item.observed_value,
            "sample_size": item.sample_size,
            "methodology": item.methodology,
            "limitations": item.limitations,
            "evidence_id": (
                f"E{evidence_sequence:03d}"
                if evidence_sequence is not None
                else None
            ),
            "evidence_quality": item.evidence_quality,
            "affected_criteria": item.affected_criteria,
            "reassessment_status": item.reassessment_status.value,
            "previous_score": item.previous_score,
            "previous_confidence": item.previous_confidence,
            "reassessed_score": item.reassessed_score,
            "reassessed_confidence": item.reassessed_confidence,
        }
        for item, evidence_sequence in rows
    ]


async def _prepare_completion_traceability(
    session: AsyncSession,
    project: Project,
    experiment: Experiment,
) -> None:
    hypothesis = await _ensure_hypothesis(session, project, experiment)
    quality = _evidence_quality(experiment)
    experiment.evidence_quality = quality
    experiment.affected_criteria = _affected_criteria(experiment, hypothesis)

    created_evidence = experiment.evidence_id is None
    if created_evidence:
        evidence = Evidence(
            project_id=project.id,
            sequence=await _next_evidence_sequence(session, project.id),
            hypothesis_id=hypothesis.id,
            agent_run_id=None,
            source=f"Experiment {experiment.id}",
            source_type="EXPERIMENT_RESULT",
            claim=_experiment_claim(experiment),
            direction=_evidence_direction(experiment.outcome),
            strength=quality,
            epistemic_classification=EpistemicClassification.FACT,
            url="",
            date=(experiment.completed_at or utc_now()).date(),
            origin=EvidenceOrigin.EXPERIMENT,
        )
        session.add(evidence)
        await session.flush()
        experiment.evidence_id = evidence.id

    if created_evidence:
        _update_hypothesis_from_result(hypothesis, experiment.outcome, quality)
    latest_score = await session.scalar(
        select(ProjectScore)
        .where(ProjectScore.project_id == project.id)
        .order_by(ProjectScore.created_at.desc(), ProjectScore.id.desc())
        .limit(1)
    )
    experiment.previous_score = latest_score.total_score if latest_score else None
    experiment.previous_confidence = latest_score.confidence if latest_score else None
    experiment.reassessed_score = None
    experiment.reassessed_confidence = None
    experiment.reassessment_score_id = None
    experiment.reassessment_decision_id = None
    experiment.reassessment_error = None
    experiment.reassessment_status = ExperimentReassessmentStatus.PENDING


async def _ensure_hypothesis(
    session: AsyncSession,
    project: Project,
    experiment: Experiment,
) -> Hypothesis:
    if experiment.hypothesis_id is not None:
        hypothesis = await session.get(Hypothesis, experiment.hypothesis_id)
        if hypothesis is not None and hypothesis.project_id == project.id:
            return hypothesis

    source_version_id = await session.scalar(
        select(IdeaVersion.id)
        .where(IdeaVersion.project_id == project.id)
        .order_by(IdeaVersion.version.desc())
        .limit(1)
    )
    hypothesis = Hypothesis(
        project_id=project.id,
        sequence=await _next_hypothesis_sequence(session, project.id),
        statement=(
            f"Experiment validates: {experiment.description} "
            f"[experiment:{experiment.id}]"
        )[:2000],
        category="EXPERIMENT",
        impact=5,
        confidence=0.5,
        status=HypothesisStatus.OPEN,
        epistemic_classification=EpistemicClassification.ASSUMPTION,
        origin=HypothesisOrigin.USER,
        source_version_id=source_version_id,
    )
    session.add(hypothesis)
    await session.flush()
    experiment.hypothesis_id = hypothesis.id
    return hypothesis


def _evidence_quality(experiment: Experiment) -> int:
    score = 0
    if experiment.success_metric and experiment.success_threshold:
        score += 1
    if experiment.outcome is not None and experiment.result_summary:
        score += 1
    if experiment.observed_value:
        score += 1
    if experiment.sample_size is not None and experiment.sample_size > 0:
        score += 1
    if experiment.methodology and len(experiment.methodology.strip()) >= 20:
        score += 1
    return min(score, 5)


def _affected_criteria(
    experiment: Experiment, hypothesis: Hypothesis
) -> list[str]:
    text = " ".join(
        filter(
            None,
            (
                experiment.experiment_type,
                experiment.description,
                experiment.success_metric,
                hypothesis.category,
                hypothesis.statement,
            ),
        )
    ).lower()
    matches: set[ScoreCriterion] = set()
    keyword_map: dict[ScoreCriterion, tuple[str, ...]] = {
        ScoreCriterion.REAL_PROBLEM: ("problem", "dor", "necessidade"),
        ScoreCriterion.PROBLEM_INTENSITY: ("urgência", "severidade", "impacto"),
        ScoreCriterion.IDENTIFIABLE_USERS: ("usuário", "user", "segmento", "persona"),
        ScoreCriterion.MARKET: ("market", "mercado", "demanda", "interview", "entrevista"),
        ScoreCriterion.DIFFERENTIATION: ("concorr", "diferencia", "competitor"),
        ScoreCriterion.TECHNICAL_FEASIBILITY: (
            "technical",
            "técnic",
            "latência",
            "latency",
            "integra",
            "backtest",
            "paper trading",
            "modelo",
            "model",
        ),
        ScoreCriterion.ECONOMIC_FEASIBILITY: (
            "custo",
            "cost",
            "receita",
            "pricing",
            "preço",
            "lucro",
            "profit",
            "p&l",
            "pnl",
            "retorno",
        ),
        ScoreCriterion.DISTRIBUTION: ("canal", "aquisição", "distribution", "vendas"),
        ScoreCriterion.DEFENSIBILITY: ("defens", "propriet", "exclusiv", "vantagem"),
        ScoreCriterion.LEGAL_REGULATORY_RISK: (
            "legal",
            "regulat",
            "compliance",
            "licença",
            "kyc",
            "aml",
        ),
        ScoreCriterion.TESTABLE_MVP: ("mvp", "protótipo", "prototype", "usability"),
        ScoreCriterion.SCALABILITY: (
            "escala",
            "scalab",
            "carga",
            "load",
            "throughput",
            "storage",
        ),
    }
    for criterion, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            matches.add(criterion)
    if not matches:
        matches.add(ScoreCriterion.TESTABLE_MVP)
    return [criterion.value for criterion in ScoreCriterion if criterion in matches]


def _experiment_claim(experiment: Experiment) -> str:
    observed = (
        f" Observed value: {experiment.observed_value}."
        if experiment.observed_value
        else ""
    )
    sample = f" Sample size: {experiment.sample_size}." if experiment.sample_size else ""
    return (
        f"Experiment outcome {experiment.outcome.value if experiment.outcome else 'UNKNOWN'} "
        f"for metric '{experiment.success_metric}' against threshold "
        f"'{experiment.success_threshold}': {experiment.result_summary}."
        f"{observed}{sample}"
    )


def _evidence_direction(outcome: ExperimentOutcome | None) -> EvidenceDirection:
    if outcome == ExperimentOutcome.SUCCESS:
        return EvidenceDirection.SUPPORT
    if outcome == ExperimentOutcome.FAILURE:
        return EvidenceDirection.CONTRADICT
    return EvidenceDirection.NEUTRAL


def _update_hypothesis_from_result(
    hypothesis: Hypothesis,
    outcome: ExperimentOutcome | None,
    quality: int,
) -> None:
    evidence_weight = quality / 5
    if outcome == ExperimentOutcome.SUCCESS:
        hypothesis.confidence = round(
            hypothesis.confidence
            + (1 - hypothesis.confidence) * 0.6 * evidence_weight,
            4,
        )
        if hypothesis.status == HypothesisStatus.REJECTED:
            hypothesis.status = HypothesisStatus.PARTIAL
        else:
            hypothesis.status = (
                HypothesisStatus.VALIDATED
                if quality >= 4
                else HypothesisStatus.PARTIAL
            )
    elif outcome == ExperimentOutcome.FAILURE:
        hypothesis.confidence = round(
            hypothesis.confidence * (1 - 0.6 * evidence_weight), 4
        )
        if hypothesis.status == HypothesisStatus.VALIDATED:
            hypothesis.status = HypothesisStatus.PARTIAL
        else:
            hypothesis.status = (
                HypothesisStatus.REJECTED
                if quality >= 4
                else HypothesisStatus.PARTIAL
            )
    else:
        hypothesis.status = HypothesisStatus.PARTIAL
    hypothesis.updated_at = utc_now()


async def _next_hypothesis_sequence(session: AsyncSession, project_id: str) -> int:
    current = await session.scalar(
        select(func.max(Hypothesis.sequence)).where(Hypothesis.project_id == project_id)
    )
    return int(current or 0) + 1


async def _next_evidence_sequence(session: AsyncSession, project_id: str) -> int:
    current = await session.scalar(
        select(func.max(Evidence.sequence)).where(Evidence.project_id == project_id)
    )
    return int(current or 0) + 1


async def _require_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


async def _require_hypothesis(
    session: AsyncSession, project_id: str, hypothesis_id: str
) -> Hypothesis:
    hypothesis = await session.get(Hypothesis, hypothesis_id)
    if hypothesis is None or hypothesis.project_id != project_id:
        raise HypothesisNotFoundError(hypothesis_id)
    return hypothesis


async def _highest_priority_hypothesis_id(
    session: AsyncSession, project_id: str
) -> str | None:
    hypotheses = list(
        (
            await session.scalars(
                select(Hypothesis).where(
                    Hypothesis.project_id == project_id,
                    Hypothesis.status.in_(
                        {HypothesisStatus.OPEN, HypothesisStatus.PARTIAL}
                    ),
                )
            )
        ).all()
    )
    if not hypotheses:
        return None
    return max(hypotheses, key=lambda item: item.priority).id
