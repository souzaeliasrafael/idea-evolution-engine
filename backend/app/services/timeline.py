from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentRun, Project, Round
from app.schemas.timeline import TimelineItemRead
from app.services.errors import ProjectNotFoundError


async def list_timeline(
    session: AsyncSession, project_id: UUID
) -> list[TimelineItemRead]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    rows = (
        await session.execute(
            select(AgentRun, Round.round_number)
            .outerjoin(Round, AgentRun.round_id == Round.id)
            .where(AgentRun.project_id == str(project_id))
            .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
        )
    ).all()
    return [
        TimelineItemRead(
            id=run.id,
            project_id=run.project_id,
            round_id=run.round_id,
            round_number=round_number,
            agent=run.agent,
            provider=run.provider,
            model=run.model,
            prompt_version=run.prompt_version,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cached_input_tokens=run.cached_input_tokens,
            reasoning_tokens=run.reasoning_tokens,
            web_search_calls=run.web_search_calls,
            tool_cost=run.tool_cost,
            web_sources=run.web_sources,
            estimated_cost=run.estimated_cost,
            succeeded=run.error is None,
            error=run.error,
            created_at=run.created_at,
        )
        for run, round_number in rows
    ]
