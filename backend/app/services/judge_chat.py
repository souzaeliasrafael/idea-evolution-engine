from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DecisionRecord,
    JudgeChatTurn,
    Project,
    ProjectScore,
    utc_now,
)
from app.domain.enums import OrchestratorStopReason
from app.schemas.judge_chat import JudgeChatTurnRead
from app.services.errors import ProjectNotFoundError


async def list_turns(
    session: AsyncSession, project_id: UUID
) -> Sequence[JudgeChatTurnRead]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    rows = (
        await session.execute(
            select(JudgeChatTurn, DecisionRecord, ProjectScore)
            .outerjoin(DecisionRecord, JudgeChatTurn.decision_id == DecisionRecord.id)
            .outerjoin(ProjectScore, DecisionRecord.score_id == ProjectScore.id)
            .where(JudgeChatTurn.project_id == str(project_id))
            .order_by(JudgeChatTurn.created_at.asc(), JudgeChatTurn.id.asc())
        )
    ).all()
    return [_to_read(turn, decision, score) for turn, decision, score in rows]


async def latest_decision_id(session: AsyncSession, project_id: UUID) -> str | None:
    return await session.scalar(
        select(DecisionRecord.id)
        .where(DecisionRecord.project_id == str(project_id))
        .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
        .limit(1)
    )


async def create_running_turn(
    session: AsyncSession,
    project: Project,
    *,
    message: str,
    input_mode: str,
) -> JudgeChatTurn:
    turn = JudgeChatTurn(
        project_id=project.id,
        user_message=message,
        input_mode=input_mode,
        status="RUNNING",
        requested_rounds=1,
        cost_before=project.total_cost,
        cost_after=project.total_cost,
    )
    project.next_round_context = _conversation_context(
        project.next_round_context, message
    )
    session.add(turn)
    await session.commit()
    await session.refresh(turn)
    return turn


async def complete_turn(
    session: AsyncSession,
    turn_id: str,
    project_id: UUID,
    *,
    previous_decision_id: str | None,
    stop_reason: OrchestratorStopReason,
) -> JudgeChatTurnRead:
    turn = await session.get(JudgeChatTurn, turn_id)
    project = await session.get(Project, str(project_id))
    if turn is None or project is None:
        raise ProjectNotFoundError(str(project_id))
    decision, score = await _latest_decision(session, project.id)
    has_new_decision = decision is not None and decision.id != previous_decision_id
    turn.stop_reason = stop_reason.value
    turn.cost_after = project.total_cost
    turn.completed_at = utc_now()
    if has_new_decision and decision is not None and score is not None:
        turn.status = "COMPLETED"
        turn.decision_id = decision.id
        turn.judge_response = _judge_response(decision, score)
    elif stop_reason == OrchestratorStopReason.USER_CANCELLED:
        turn.status = "CANCELLED"
        turn.judge_response = (
            "A execução foi interrompida com segurança antes de um novo julgamento. "
            "Sua mensagem ficou salva para uma próxima tentativa."
        )
        decision = None
        score = None
    elif stop_reason == OrchestratorStopReason.BUDGET_LIMIT_REACHED:
        turn.status = "BUDGET_STOPPED"
        turn.judge_response = (
            "O orçamento terminou antes de eu produzir um novo julgamento. "
            "Sua mensagem ficou salva; aumente o teto do projeto para continuar."
        )
        decision = None
        score = None
    else:
        turn.status = "NO_DECISION"
        turn.judge_response = (
            "O ciclo terminou sem uma nova decisão do Judge. Sua mensagem ficou "
            "registrada no projeto."
        )
        decision = None
        score = None
    await session.commit()
    await session.refresh(turn)
    return _to_read(turn, decision, score)


async def fail_turn(
    session: AsyncSession, turn_id: str, *, error: str
) -> None:
    await session.rollback()
    turn = await session.get(JudgeChatTurn, turn_id)
    if turn is None:
        return
    project = await session.get(Project, turn.project_id)
    turn.status = "FAILED"
    turn.error = error[:4000]
    turn.judge_response = (
        "O ciclo encontrou um erro antes de um novo julgamento. Sua mensagem foi "
        "preservada para você tentar novamente."
    )
    turn.cost_after = project.total_cost if project is not None else turn.cost_before
    turn.completed_at = utc_now()
    await session.commit()


async def _latest_decision(
    session: AsyncSession, project_id: str
) -> tuple[DecisionRecord | None, ProjectScore | None]:
    row = (
        await session.execute(
            select(DecisionRecord, ProjectScore)
            .join(ProjectScore, DecisionRecord.score_id == ProjectScore.id)
            .where(DecisionRecord.project_id == project_id)
            .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
            .limit(1)
        )
    ).first()
    return (None, None) if row is None else (row[0], row[1])


def _conversation_context(existing: str | None, message: str) -> str:
    block = (
        "[CONVERSA COM O JUDGE — NOVA MENSAGEM DO USUÁRIO]\n"
        f"{message}\n"
        "Use esta mensagem como orientação e informação fornecida pelo usuário. "
        "Todos os agentes devem considerá-la, e o Judge deve respondê-la por meio "
        "de sua decisão final, score, confiança e próximas ações."
    )
    return f"{existing.strip()}\n\n{block}" if existing and existing.strip() else block


def _judge_response(decision: DecisionRecord, score: ProjectScore) -> str:
    labels = {
        "REFINE": "refinar a proposta",
        "RESEARCH": "pesquisar mais",
        "TEST": "testar a hipótese principal",
        "PIVOT": "pivotar a proposta",
        "APPROVE": "aprovar a proposta",
        "DISCARD": "descartar a proposta",
    }
    decision_value = decision.decision.value
    response = (
        f"Depois de passar sua mensagem pelo ciclo completo, minha decisão é "
        f"{labels[decision_value]}. O score é {score.total_score} de 100, com "
        f"{round(score.confidence * 100)} por cento de confiança. {decision.reason}"
    )
    if decision.critical_blockers:
        response += f" Principal bloqueio: {decision.critical_blockers[0]}."
    if decision.next_actions:
        response += f" Próximo passo recomendado: {decision.next_actions[0]}."
    return response


def _to_read(
    turn: JudgeChatTurn,
    decision: DecisionRecord | None,
    score: ProjectScore | None,
) -> JudgeChatTurnRead:
    return JudgeChatTurnRead(
        id=turn.id,
        project_id=turn.project_id,
        decision_id=turn.decision_id,
        user_message=turn.user_message,
        input_mode=turn.input_mode,
        status=turn.status,
        requested_rounds=turn.requested_rounds,
        judge_response=turn.judge_response,
        stop_reason=turn.stop_reason,
        error=turn.error,
        decision=decision.decision if decision is not None else None,
        score=score.total_score if score is not None else None,
        confidence=score.confidence if score is not None else None,
        cost_before=turn.cost_before,
        cost_after=turn.cost_after,
        created_at=turn.created_at,
        completed_at=turn.completed_at,
    )
