from collections import defaultdict
from decimal import Decimal
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentRun, Project, Round
from app.schemas.operations import (
    AgentMetricRead,
    ProjectEfficiencyRead,
    ProjectMetricsRead,
    RoundEfficiencyRead,
)
from app.services.errors import ProjectNotFoundError


async def project_metrics(
    session: AsyncSession, project_id: UUID
) -> ProjectMetricsRead:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    runs = list(
        (
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.project_id == project.id)
                .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            )
        ).all()
    )
    groups: dict[tuple[object, str, str], list[AgentRun]] = defaultdict(list)
    for run in runs:
        groups[(run.agent, run.provider, run.model)].append(run)
    by_agent = [
        AgentMetricRead(
            agent=agent,
            provider=provider,
            model=model,
            runs=len(items),
            successful_runs=sum(item.error is None for item in items),
            failed_runs=sum(item.error is not None for item in items),
            input_tokens=sum(item.input_tokens for item in items),
            output_tokens=sum(item.output_tokens for item in items),
            cached_input_tokens=sum(item.cached_input_tokens for item in items),
            reasoning_tokens=sum(item.reasoning_tokens for item in items),
            estimated_cost=sum(
                (item.estimated_cost for item in items), Decimal("0")
            ),
            average_execution_time=(
                sum(item.execution_time for item in items) / len(items)
            ),
        )
        for (agent, provider, model), items in sorted(
            groups.items(), key=lambda item: (item[0][0].value, item[0][1], item[0][2])
        )
    ]
    return ProjectMetricsRead(
        project_id=project.id,
        total_runs=len(runs),
        total_input_tokens=sum(item.input_tokens for item in runs),
        total_output_tokens=sum(item.output_tokens for item in runs),
        total_estimated_cost=sum(
            (item.estimated_cost for item in runs), Decimal("0")
        ),
        by_agent=by_agent,
    )


async def project_efficiency(
    session: AsyncSession, project_id: UUID
) -> ProjectEfficiencyRead:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    rounds = list(
        (
            await session.scalars(
                select(Round)
                .where(Round.project_id == project.id)
                .order_by(Round.round_number.asc())
            )
        ).all()
    )
    runs = list(
        (
            await session.scalars(
                select(AgentRun).where(
                    AgentRun.project_id == project.id,
                    AgentRun.round_id.is_not(None),
                )
            )
        ).all()
    )
    runs_by_round: dict[str, list[AgentRun]] = defaultdict(list)
    for run in runs:
        if run.round_id is not None:
            runs_by_round[run.round_id].append(run)

    items: list[RoundEfficiencyRead] = []
    previous_score: int | None = None
    previous_confidence: float | None = None
    for round_record in rounds:
        round_runs = runs_by_round[round_record.id]
        payload_sizes = [
            len(json.dumps(run.input_json, ensure_ascii=False, separators=(",", ":")))
            for run in round_runs
        ]
        score_delta = (
            round_record.score - previous_score
            if round_record.score is not None and previous_score is not None
            else None
        )
        confidence_delta = (
            round_record.confidence - previous_confidence
            if round_record.confidence is not None and previous_confidence is not None
            else None
        )
        cost = sum(
            (Decimal(run.estimated_cost) for run in round_runs), Decimal("0")
        )
        cost_per_point = (
            (cost / Decimal(score_delta)).quantize(Decimal("0.000001"))
            if score_delta is not None and score_delta > 0
            else None
        )
        items.append(
            RoundEfficiencyRead(
                round_number=round_record.round_number,
                status=round_record.status.value,
                calls=len(round_runs),
                failed_calls=sum(run.error is not None for run in round_runs),
                input_tokens=sum(run.input_tokens for run in round_runs),
                cached_input_tokens=sum(run.cached_input_tokens for run in round_runs),
                output_tokens=sum(run.output_tokens for run in round_runs),
                reasoning_tokens=sum(run.reasoning_tokens for run in round_runs),
                input_payload_characters=sum(payload_sizes),
                largest_input_payload_characters=max(payload_sizes, default=0),
                estimated_cost=cost,
                score=round_record.score,
                confidence=round_record.confidence,
                score_delta=score_delta,
                confidence_delta=confidence_delta,
                cost_per_score_point=cost_per_point,
            )
        )
        if round_record.score is not None:
            previous_score = round_record.score
        if round_record.confidence is not None:
            previous_confidence = round_record.confidence

    recommendation, reason = _efficiency_recommendation(items)
    return ProjectEfficiencyRead(
        project_id=project.id,
        rounds=items,
        total_round_cost=sum(
            (item.estimated_cost for item in items), Decimal("0")
        ),
        recommendation=recommendation,
        recommendation_reason=reason,
    )


def _efficiency_recommendation(
    items: list[RoundEfficiencyRead],
) -> tuple[str, str]:
    if not items:
        return "SEM_DADOS", "Execute a primeira rodada para criar uma referência."
    latest_run = items[-1]
    if latest_run.status in {"FAILED", "CANCELLED"}:
        return "CORRIGIR_EXECUCAO", "A última rodada não terminou; corrija ou retome antes de comparar valor."
    scored = [item for item in items if item.score is not None]
    if not scored:
        return "SEM_JULGAMENTO", "Nenhuma rodada chegou a um score comparável; revise as falhas antes de gastar novamente."
    latest = scored[-1]
    if latest.score is not None and latest.score >= 80 and (latest.confidence or 0) >= 0.7:
        return "PARAR_E_DECIDIR", "Score e confiança já estão altos; decida antes de pagar por outra rodada."
    if latest.score_delta is None:
        return "CRIAR_REFERENCIA", "Ainda existe somente uma rodada; a próxima cria a primeira comparação."
    if latest.score_delta >= 2 or (latest.confidence_delta or 0) >= 0.05:
        return "CONTINUAR_SE_HOUVER_INFORMACAO_NOVA", "A rodada gerou ganho mensurável; outra pode valer a pena com novos dados."
    if latest.score_delta <= 0 and (latest.confidence_delta or 0) <= 0.01:
        suffix = (
            " Rodadas posteriores não chegaram a um novo julgamento."
            if latest.round_number != latest_run.round_number
            else ""
        )
        return "ADICIONAR_EVIDENCIA_ANTES", (
            "A última rodada comparável não produziu ganho relevante de score ou confiança."
            + suffix
        )
    return "CONTINUAR_COM_CRITERIO", "O ganho foi pequeno; só rode novamente com uma pergunta ou evidência nova."
