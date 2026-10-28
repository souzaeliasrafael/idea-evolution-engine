from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AgentRun,
    Criticism,
    DecisionRecord,
    DevelopmentBlueprint,
    Evidence,
    Experiment,
    ImprovementPlan,
    JudgeChatTurn,
    Hypothesis,
    IdeaVersion,
    Project,
    ProjectScore,
    Round,
)
from app.schemas.operations import ProjectBackup
from app.schemas.project import AgentExecutionPlan
from app.services.errors import BackupValidationError, ProjectNotFoundError


BACKUP_SCHEMA_VERSION = "1.4"
PROJECT_TABLES = (
    ("projects", Project),
    ("idea_versions", IdeaVersion),
    ("rounds", Round),
    ("agent_runs", AgentRun),
    ("hypotheses", Hypothesis),
    ("evidence", Evidence),
    ("criticisms", Criticism),
    ("scores", ProjectScore),
    ("decisions", DecisionRecord),
    ("judge_chat_turns", JudgeChatTurn),
    ("improvement_plans", ImprovementPlan),
    ("experiments", Experiment),
    ("development_blueprints", DevelopmentBlueprint),
)


async def export_project(
    session: AsyncSession, project_id: UUID
) -> ProjectBackup:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    data: dict[str, list[dict[str, Any]]] = {"projects": [_dump_row(project)]}
    for name, model in PROJECT_TABLES[1:]:
        rows = (
            await session.scalars(
                select(model).where(model.project_id == project.id)  # type: ignore[attr-defined]
            )
        ).all()
        data[name] = [_dump_row(row) for row in rows]
    return ProjectBackup(
        schema_version=BACKUP_SCHEMA_VERSION,
        exported_at=datetime.now(UTC),
        data=data,
    )


async def import_project(session: AsyncSession, backup: ProjectBackup) -> Project:
    if backup.schema_version not in {"1.0", "1.1", "1.2", "1.3", BACKUP_SCHEMA_VERSION}:
        raise BackupValidationError(
            f"Unsupported backup schema: {backup.schema_version}"
        )
    expected = {name for name, _ in PROJECT_TABLES}
    if backup.schema_version == "1.0":
        expected.remove("development_blueprints")
    if backup.schema_version in {"1.0", "1.1", "1.2"}:
        expected.remove("improvement_plans")
    if backup.schema_version != BACKUP_SCHEMA_VERSION:
        expected.remove("judge_chat_turns")
    if set(backup.data) != expected or len(backup.data["projects"]) != 1:
        raise BackupValidationError("Backup has an invalid project table set")

    try:
        source_project = backup.data["projects"][0]
        project = Project(
            id=str(uuid4()),
            name=f"{_text(source_project, 'name')} (restored)",
            raw_idea=_text(source_project, "raw_idea"),
            status=_text(source_project, "status"),
            total_cost=_decimal(source_project, "total_cost"),
            max_ai_budget=_optional_decimal(source_project, "max_ai_budget"),
            next_round_context=source_project.get("next_round_context"),
            stagnation_detected=bool(source_project.get("stagnation_detected", False)),
            agent_profile_id=None,
            agent_plan=AgentExecutionPlan.model_validate(
                source_project.get("agent_plan", {})
            ).model_dump(),
            created_at=_datetime(source_project, "created_at"),
            updated_at=_datetime(source_project, "updated_at"),
        )
        session.add(project)
        await session.flush()

        version_ids: dict[str, str] = {}
        for source in sorted(
            backup.data["idea_versions"], key=lambda item: int(item["version"])
        ):
            new_id = str(uuid4())
            version_ids[_text(source, "id")] = new_id
            session.add(
                IdeaVersion(
                    id=new_id,
                    project_id=project.id,
                    version=int(source["version"]),
                    parent_version_id=_mapped_optional(
                        version_ids, source.get("parent_version_id")
                    ),
                    reason_for_change=_text(source, "reason_for_change"),
                    created_by=_text(source, "created_by"),
                    changes=list(source.get("changes", [])),
                    concept=dict(source.get("concept", {})),
                    created_at=_datetime(source, "created_at"),
                )
            )
        await session.flush()

        round_ids: dict[str, str] = {}
        for source in sorted(
            backup.data["rounds"], key=lambda item: int(item["round_number"])
        ):
            new_id = str(uuid4())
            round_ids[_text(source, "id")] = new_id
            session.add(
                Round(
                    id=new_id,
                    project_id=project.id,
                    round_number=int(source["round_number"]),
                    status=_text(source, "status"),
                    starting_version_id=version_ids[_text(source, "starting_version_id")],
                    resulting_version_id=_mapped_optional(
                        version_ids, source.get("resulting_version_id")
                    ),
                    decision=source.get("decision"),
                    score=source.get("score"),
                    confidence=source.get("confidence"),
                    budget_limit_reached=bool(
                        source.get("budget_limit_reached", False)
                    ),
                    stagnation_detected=bool(
                        source.get("stagnation_detected", False)
                    ),
                    error=source.get("error"),
                    human_context=source.get("human_context"),
                    started_at=_datetime(source, "started_at"),
                    completed_at=_optional_datetime(source.get("completed_at")),
                )
            )
        await session.flush()

        run_ids: dict[str, str] = {}
        for source in backup.data["agent_runs"]:
            new_id = str(uuid4())
            run_ids[_text(source, "id")] = new_id
            session.add(
                AgentRun(
                    id=new_id,
                    project_id=project.id,
                    round_id=_mapped_optional(round_ids, source.get("round_id")),
                    agent=_text(source, "agent"),
                    provider=str(source.get("provider") or "unknown"),
                    model=_text(source, "model"),
                    prompt_version=_text(source, "prompt_version"),
                    input_json=dict(source.get("input_json", {})),
                    output_json=(
                        dict(source["output_json"])
                        if source.get("output_json") is not None
                        else None
                    ),
                    input_tokens=int(source.get("input_tokens", 0)),
                    output_tokens=int(source.get("output_tokens", 0)),
                    cached_input_tokens=int(source.get("cached_input_tokens", 0)),
                    reasoning_tokens=int(source.get("reasoning_tokens", 0)),
                    web_search_calls=int(source.get("web_search_calls", 0)),
                    tool_cost=_decimal(source, "tool_cost"),
                    web_sources=list(source.get("web_sources", [])),
                    estimated_cost=_decimal(source, "estimated_cost"),
                    execution_time=float(source.get("execution_time", 0)),
                    error=source.get("error"),
                    created_at=_datetime(source, "created_at"),
                )
            )
        await session.flush()

        hypothesis_ids: dict[str, str] = {}
        for source in sorted(
            backup.data["hypotheses"], key=lambda item: int(item["sequence"])
        ):
            new_id = str(uuid4())
            hypothesis_ids[_text(source, "id")] = new_id
            session.add(
                Hypothesis(
                    id=new_id,
                    project_id=project.id,
                    sequence=int(source["sequence"]),
                    statement=_text(source, "statement"),
                    category=_text(source, "category"),
                    impact=int(source["impact"]),
                    confidence=float(source["confidence"]),
                    status=_text(source, "status"),
                    epistemic_classification=_text(
                        source, "epistemic_classification"
                    ),
                    origin=_text(source, "origin"),
                    source_version_id=_mapped_optional(
                        version_ids, source.get("source_version_id")
                    ),
                    created_at=_datetime(source, "created_at"),
                    updated_at=_datetime(source, "updated_at"),
                )
            )
        await session.flush()

        evidence_ids: dict[str, str] = {}
        for source in backup.data["evidence"]:
            new_id = str(uuid4())
            evidence_ids[_text(source, "id")] = new_id
            session.add(
                Evidence(
                    id=new_id,
                    project_id=project.id,
                    sequence=int(source["sequence"]),
                    hypothesis_id=hypothesis_ids[_text(source, "hypothesis_id")],
                    agent_run_id=_mapped_optional(
                        run_ids, source.get("agent_run_id")
                    ),
                    source=_text(source, "source"),
                    source_type=_text(source, "source_type"),
                    claim=_text(source, "claim"),
                    direction=_text(source, "direction"),
                    strength=int(source["strength"]),
                    epistemic_classification=_text(
                        source, "epistemic_classification"
                    ),
                    url=str(source.get("url", "")),
                    date=_optional_date(source.get("date")),
                    origin=_text(source, "origin"),
                    created_at=_datetime(source, "created_at"),
                )
            )

        for source in backup.data["criticisms"]:
            session.add(
                Criticism(
                    id=str(uuid4()),
                    project_id=project.id,
                    idea_version_id=version_ids[_text(source, "idea_version_id")],
                    agent_run_id=run_ids[_text(source, "agent_run_id")],
                    title=_text(source, "title"),
                    severity=_text(source, "severity"),
                    claim=_text(source, "claim"),
                    reason=_text(source, "reason"),
                    affected_hypotheses=list(
                        source.get("affected_hypotheses", [])
                    ),
                    evidence_needed=_text(source, "evidence_needed"),
                    condition_that_refutes_criticism=_text(
                        source, "condition_that_refutes_criticism"
                    ),
                    created_at=_datetime(source, "created_at"),
                )
            )

        score_ids: dict[str, str] = {}
        for source in backup.data["scores"]:
            new_id = str(uuid4())
            score_ids[_text(source, "id")] = new_id
            session.add(
                ProjectScore(
                    id=new_id,
                    project_id=project.id,
                    idea_version_id=version_ids[_text(source, "idea_version_id")],
                    agent_run_id=run_ids[_text(source, "agent_run_id")],
                    total_score=int(source["total_score"]),
                    confidence=float(source["confidence"]),
                    breakdown=list(source.get("breakdown", [])),
                    created_at=_datetime(source, "created_at"),
                )
            )
        await session.flush()

        decision_ids: dict[str, str] = {}
        for source in backup.data["decisions"]:
            new_id = str(uuid4())
            decision_ids[_text(source, "id")] = new_id
            session.add(
                DecisionRecord(
                    id=new_id,
                    project_id=project.id,
                    round_number=source.get("round_number"),
                    decision=_text(source, "decision"),
                    reason=_text(source, "reason"),
                    from_version_id=version_ids[_text(source, "from_version_id")],
                    to_version_id=_mapped_optional(
                        version_ids, source.get("to_version_id")
                    ),
                    score_id=score_ids[_text(source, "score_id")],
                    agent_run_id=run_ids[_text(source, "agent_run_id")],
                    critical_blockers=list(source.get("critical_blockers", [])),
                    most_important_unknowns=list(
                        source.get("most_important_unknowns", [])
                    ),
                    next_actions=list(source.get("next_actions", [])),
                    human_review_status=_text(source, "human_review_status"),
                    human_action=source.get("human_action"),
                    human_note=source.get("human_note"),
                    reviewed_at=_optional_datetime(source.get("reviewed_at")),
                    created_at=_datetime(source, "created_at"),
                )
            )
        await session.flush()

        for source in backup.data.get("judge_chat_turns", []):
            session.add(
                JudgeChatTurn(
                    id=str(uuid4()),
                    project_id=project.id,
                    decision_id=_mapped_optional(
                        decision_ids, source.get("decision_id")
                    ),
                    user_message=_text(source, "user_message"),
                    input_mode=_text(source, "input_mode"),
                    status=_text(source, "status"),
                    requested_rounds=int(source.get("requested_rounds", 1)),
                    judge_response=source.get("judge_response"),
                    stop_reason=source.get("stop_reason"),
                    error=source.get("error"),
                    cost_before=_decimal(source, "cost_before"),
                    cost_after=_decimal(source, "cost_after"),
                    created_at=_datetime(source, "created_at"),
                    completed_at=_optional_datetime(source.get("completed_at")),
                )
            )

        for source in backup.data.get("improvement_plans", []):
            session.add(
                ImprovementPlan(
                    id=str(uuid4()),
                    project_id=project.id,
                    round_id=_mapped_optional(round_ids, source.get("round_id")),
                    idea_version_id=version_ids[_text(source, "idea_version_id")],
                    score_id=score_ids[_text(source, "score_id")],
                    decision_id=decision_ids[_text(source, "decision_id")],
                    agent_run_id=run_ids[_text(source, "agent_run_id")],
                    version=int(source["version"]),
                    source_score=int(source["source_score"]),
                    source_confidence=float(source["source_confidence"]),
                    plan=dict(source.get("plan", {})),
                    created_at=_datetime(source, "created_at"),
                )
            )

        for source in backup.data["experiments"]:
            session.add(
                Experiment(
                    id=str(uuid4()),
                    project_id=project.id,
                    decision_id=_mapped_optional(
                        decision_ids, source.get("decision_id")
                    ),
                    hypothesis_id=_mapped_optional(
                        hypothesis_ids, source.get("hypothesis_id")
                    ),
                    experiment_type=_text(source, "experiment_type"),
                    description=_text(source, "description"),
                    success_metric=source.get("success_metric"),
                    success_threshold=source.get("success_threshold"),
                    estimated_cost=_decimal(source, "estimated_cost"),
                    actual_cost=_decimal(source, "actual_cost"),
                    status=_text(source, "status"),
                    outcome=source.get("outcome"),
                    result_summary=source.get("result_summary"),
                    observed_value=source.get("observed_value"),
                    sample_size=source.get("sample_size"),
                    methodology=source.get("methodology"),
                    limitations=source.get("limitations"),
                    evidence_id=_mapped_optional(
                        evidence_ids, source.get("evidence_id")
                    ),
                    evidence_quality=source.get("evidence_quality"),
                    affected_criteria=list(source.get("affected_criteria", [])),
                    reassessment_status=source.get(
                        "reassessment_status", "NOT_REQUESTED"
                    ),
                    previous_score=source.get("previous_score"),
                    previous_confidence=source.get("previous_confidence"),
                    reassessed_score=source.get("reassessed_score"),
                    reassessed_confidence=source.get("reassessed_confidence"),
                    reassessment_score_id=_mapped_optional(
                        score_ids, source.get("reassessment_score_id")
                    ),
                    reassessment_decision_id=_mapped_optional(
                        decision_ids, source.get("reassessment_decision_id")
                    ),
                    reassessment_error=source.get("reassessment_error"),
                    created_at=_datetime(source, "created_at"),
                    updated_at=_datetime(source, "updated_at"),
                    completed_at=_optional_datetime(source.get("completed_at")),
                )
            )

        for source in backup.data.get("development_blueprints", []):
            session.add(
                DevelopmentBlueprint(
                    id=str(uuid4()),
                    project_id=project.id,
                    version=int(source["version"]),
                    status=_text(source, "status"),
                    architecture_alternatives=int(
                        source["architecture_alternatives"]
                    ),
                    user_context=source.get("user_context"),
                    max_ai_budget=_optional_decimal(source, "max_ai_budget"),
                    estimated_cost=_decimal(source, "estimated_cost"),
                    product_definition=(
                        dict(source["product_definition"])
                        if source.get("product_definition") is not None
                        else None
                    ),
                    architecture_options=list(
                        source.get("architecture_options", [])
                    ),
                    technical_review=(
                        dict(source["technical_review"])
                        if source.get("technical_review") is not None
                        else None
                    ),
                    final_blueprint=(
                        dict(source["final_blueprint"])
                        if source.get("final_blueprint") is not None
                        else None
                    ),
                    agent_run_ids=[
                        run_ids[item]
                        for item in source.get("agent_run_ids", [])
                        if item in run_ids
                    ],
                    error=source.get("error"),
                    created_at=_datetime(source, "created_at"),
                    completed_at=_optional_datetime(source.get("completed_at")),
                )
            )

        await session.commit()
        await session.refresh(project)
        return project
    except (KeyError, TypeError, ValueError) as exc:
        await session.rollback()
        raise BackupValidationError("Backup payload is incomplete or invalid") from exc


def _dump_row(row: object) -> dict[str, Any]:
    return {
        column.name: _json_value(getattr(row, column.name))
        for column in row.__table__.columns  # type: ignore[attr-defined]
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _text(source: dict[str, Any], key: str) -> str:
    value = source[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _decimal(source: dict[str, Any], key: str) -> Decimal:
    return Decimal(str(source.get(key, "0")))


def _optional_decimal(source: dict[str, Any], key: str) -> Decimal | None:
    return None if source.get(key) is None else Decimal(str(source[key]))


def _datetime(source: dict[str, Any], key: str) -> datetime:
    value = _optional_datetime(source.get(key))
    if value is None:
        raise ValueError(f"{key} must be a datetime")
    return value


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _optional_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _mapped_optional(mapping: dict[str, str], value: Any) -> str | None:
    return None if value is None else mapping[str(value)]
