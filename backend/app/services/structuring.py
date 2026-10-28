from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.structurer import (
    IdeaStructurer,
)
from app.agents.base import AgentExecutionError
from app.core.config import get_settings
from app.database.models import IdeaVersion, Project
from app.domain.enums import AgentType, HypothesisOrigin
from app.llm.base import LLMProvider
from app.services.agent_runs import add_agent_runs
from app.services.budget import refresh_budget, require_budget_available
from app.services.errors import (
    AgentExecutionFailedError,
    ProjectAlreadyStructuredError,
    ProjectNotFoundError,
)
from app.services.knowledge import register_concept_hypotheses
from app.services.prompts import get_effective_prompt


async def structure_project(
    session: AsyncSession, project_id: UUID, provider: LLMProvider
) -> IdeaVersion:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    await refresh_budget(session, project)
    require_budget_available(project)

    existing_version_id = await session.scalar(
        select(IdeaVersion.id)
        .where(IdeaVersion.project_id == str(project_id))
        .limit(1)
    )
    if existing_version_id is not None:
        raise ProjectAlreadyStructuredError(str(project_id))

    effective_prompt = await get_effective_prompt(session, AgentType.STRUCTURER)
    settings = get_settings()
    structurer = IdeaStructurer(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
    )
    try:
        result = await structurer.run(project_name=project.name, raw_idea=project.raw_idea)
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=str(project_id),
            agent=AgentType.STRUCTURER,
            provider=provider,
            prompt_version=structurer.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project_id,
            agent=AgentType.STRUCTURER.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    await add_agent_runs(
        session,
        project_id=str(project_id),
        agent=AgentType.STRUCTURER,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
    )
    version = IdeaVersion(
        project_id=str(project_id),
        version=0,
        parent_version_id=None,
        reason_for_change="Initial structuring of the raw idea",
        created_by=AgentType.STRUCTURER,
        changes=["Created the initial structured concept from the raw idea"],
        concept=result.output.model_dump(mode="json"),
    )
    session.add(version)
    await session.flush()
    await register_concept_hypotheses(
        session,
        project_id=str(project_id),
        source_version_id=version.id,
        concept=result.output.model_dump(mode="json"),
        origin=HypothesisOrigin.STRUCTURER,
    )
    await session.commit()
    await session.refresh(version)
    return version


async def list_idea_versions(
    session: AsyncSession, project_id: UUID
) -> Sequence[IdeaVersion]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))

    result = await session.scalars(
        select(IdeaVersion)
        .where(IdeaVersion.project_id == str(project_id))
        .order_by(IdeaVersion.version.asc())
    )
    return result.all()
