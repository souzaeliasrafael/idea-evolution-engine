from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.idea import IdeaVersionRead
from app.schemas.operations import ProjectReportRead
from app.schemas.project import ProjectRead
from app.services import development, evaluation, experiments, improvements, judge_chat, judging, knowledge, metrics, timeline
from app.orchestration import orchestrator
from app.services import projects as project_service
from app.services import structuring
from app.services.errors import ProjectNotFoundError


async def build_report(
    session: AsyncSession, project_id: UUID
) -> ProjectReportRead:
    project = await project_service.get_project(session, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    versions = list(await structuring.list_idea_versions(session, project_id))
    scores = list(await judging.list_scores(session, project_id))
    decisions = await judging.list_decisions(session, project_id)
    judge_chat_rows = list(await judge_chat.list_turns(session, project_id))
    rounds = list(await orchestrator.list_rounds(session, project_id))
    hypotheses = await knowledge.list_hypotheses(session, project_id)
    evidence = await knowledge.list_evidence(session, project_id)
    criticisms = list(await evaluation.list_criticisms(session, project_id))
    experiment_rows = list(await experiments.list_experiments(session, project_id))
    improvement_rows = list(
        await improvements.list_improvement_plans(session, project_id)
    )
    blueprint_rows = list(await development.list_blueprints(session, project_id))
    timeline_rows = await timeline.list_timeline(session, project_id)
    project_metrics = await metrics.project_metrics(session, project_id)
    typed_versions = [IdeaVersionRead.model_validate(item) for item in versions]
    return ProjectReportRead(
        generated_at=datetime.now(UTC),
        project=ProjectRead.model_validate(project),
        current_version=typed_versions[-1] if typed_versions else None,
        versions=typed_versions,
        scores=scores,
        decisions=decisions,
        judge_chat_turns=judge_chat_rows,
        rounds=rounds,
        hypotheses=hypotheses,
        evidence=evidence,
        criticisms=criticisms,
        experiments=experiment_rows,
        improvement_plans=improvement_rows,
        development_blueprints=blueprint_rows,
        timeline=timeline_rows,
        metrics=project_metrics,
    )


def render_markdown(report: ProjectReportRead) -> str:
    project = report.project
    version = report.current_version
    latest_score = report.scores[-1] if report.scores else None
    latest_decision = report.decisions[-1] if report.decisions else None
    lines = [
        f"# {project.name}",
        "",
        f"- Status: **{project.status.value}**",
        f"- Score: **{latest_score.total_score if latest_score else '—'}**",
        f"- Confidence: **{latest_score.confidence if latest_score else '—'}**",
        f"- AI cost: **${project.total_cost}**",
        f"- Generated: **{report.generated_at.isoformat()}**",
        "",
        "## Original idea",
        "",
        project.raw_idea,
    ]
    if version is not None:
        lines.extend(
            [
                "",
                f"## Current concept — V{version.version}",
                "",
                f"### Problem\n\n{version.concept.problem}",
                "",
                f"### Solution\n\n{version.concept.solution}",
                "",
                f"### Value proposition\n\n{version.concept.value_proposition}",
                "",
                f"### Initial MVP\n\n{version.concept.initial_mvp}",
            ]
        )
    if latest_decision is not None:
        lines.extend(
            [
                "",
                "## Latest decision",
                "",
                f"**{latest_decision.decision.value}** — {latest_decision.reason}",
                "",
                f"Human review: **{latest_decision.human_review_status.value}**",
            ]
        )
    lines.extend(["", "## Conversation with the Judge", ""])
    for turn in report.judge_chat_turns:
        lines.extend(
            [
                f"### User ({turn.input_mode.lower()}) — {turn.created_at.isoformat()}",
                "",
                turn.user_message,
                "",
                f"**Judge:** {turn.judge_response or turn.error or turn.status}",
            ]
        )
    if not report.judge_chat_turns:
        lines.append("No Judge conversation recorded.")
    lines.extend(["", "## Critical problems", ""])
    lines.extend(
        f"- **{item.severity.value} — {item.title}:** {item.claim}"
        for item in report.criticisms
    )
    if not report.criticisms:
        lines.append("No criticisms recorded.")
    lines.extend(["", "## Hypotheses", ""])
    lines.extend(
        f"- **{item.id}** {item.statement} — priority {item.priority:.2f}, {item.status.value}"
        for item in report.hypotheses
    )
    if not report.hypotheses:
        lines.append("No hypotheses recorded.")
    lines.extend(["", "## Experiments", ""])
    lines.extend(
        f"- **{item.status.value}** {item.description}"
        + (f" — {item.outcome.value}: {item.result_summary}" if item.outcome else "")
        + (
            f" — evidence quality {item.evidence_quality}/5; affected: "
            + ", ".join(criterion.value for criterion in item.affected_criteria)
            if item.evidence_quality is not None
            else ""
        )
        + (
            f" — reassessed score {item.previous_score} → {item.reassessed_score}; "
            f"confidence {item.previous_confidence} → {item.reassessed_confidence}"
            if item.reassessed_score is not None
            else ""
        )
        for item in report.experiments
    )
    if not report.experiments:
        lines.append("No experiments recorded.")
    lines.extend(["", "## Improvement plans", ""])
    if report.improvement_plans:
        plan = report.improvement_plans[0]
        lines.extend(
            [
                f"Latest: **V{plan.version} · source score {plan.source_score}**",
                "",
                plan.plan.summary,
                "",
                f"Recommended strategy: **{plan.plan.recommended_strategy}**",
                "",
            ]
        )
        lines.extend(
            f"- **{item.title}:** {item.description}"
            for item in plan.plan.proposals
        )
    else:
        lines.append("No improvement plan generated.")
    lines.extend(["", "## Development blueprints", ""])
    if report.development_blueprints:
        blueprint = report.development_blueprints[0]
        lines.append(
            f"Latest: **V{blueprint.version} · {blueprint.status.value}** — ${blueprint.estimated_cost}"
        )
        if blueprint.final_blueprint is not None:
            lines.extend(
                [
                    "",
                    f"Selected architecture: **{blueprint.final_blueprint.selected_option}**",
                    "",
                    blueprint.final_blueprint.decision_rationale,
                    "",
                    "### Delivery phases",
                    "",
                ]
            )
            lines.extend(
                f"- **Phase {phase.number} — {phase.name}:** {phase.objective}"
                for phase in blueprint.final_blueprint.phases
            )
    else:
        lines.append("No development blueprint generated.")
    return "\n".join(lines) + "\n"
