from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentProfile, Project, WorkflowExecution
from app.schemas.profiles import ProjectProfileUpdate
from app.schemas.project import (
    ProjectAgentPlanUpdate,
    ProjectBudgetUpdate,
    ProjectCreate,
    ProjectNextRoundContextUpdate,
)
from app.services.errors import AgentProfileNotFoundError


async def create_project(session: AsyncSession, payload: ProjectCreate) -> Project:
    if payload.agent_profile_id is not None and await session.get(
        AgentProfile, str(payload.agent_profile_id)
    ) is None:
        raise AgentProfileNotFoundError(str(payload.agent_profile_id))
    project = Project(
        name=payload.name,
        raw_idea=payload.raw_idea,
        max_ai_budget=payload.max_ai_budget,
        agent_profile_id=(
            str(payload.agent_profile_id) if payload.agent_profile_id else None
        ),
        agent_plan=payload.agent_plan.model_dump(),
    )
    session.add(project)
    await session.flush()
    session.add(WorkflowExecution(project_id=project.id))
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession, *, offset: int = 0, limit: int = 50
) -> Sequence[Project]:
    result = await session.scalars(
        select(Project)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.all()


async def get_project(session: AsyncSession, project_id: UUID) -> Project | None:
    return await session.get(Project, str(project_id))


async def update_project_budget(
    session: AsyncSession, project_id: UUID, payload: ProjectBudgetUpdate
) -> Project | None:
    project = await get_project(session, project_id)
    if project is None:
        return None
    project.max_ai_budget = payload.max_ai_budget
    await session.commit()
    await session.refresh(project)
    return project


async def update_project_agent_plan(
    session: AsyncSession, project_id: UUID, payload: ProjectAgentPlanUpdate
) -> Project | None:
    project = await get_project(session, project_id)
    if project is None:
        return None
    project.agent_plan = payload.agent_plan.model_dump()
    await session.commit()
    await session.refresh(project)
    return project


async def update_next_round_context(
    session: AsyncSession,
    project_id: UUID,
    payload: ProjectNextRoundContextUpdate,
) -> Project | None:
    project = await get_project(session, project_id)
    if project is None:
        return None
    project.next_round_context = payload.next_round_context
    await session.commit()
    await session.refresh(project)
    return project


async def update_project_profile(
    session: AsyncSession, project_id: UUID, payload: ProjectProfileUpdate
) -> Project | None:
    project = await get_project(session, project_id)
    if project is None:
        return None
    if payload.agent_profile_id is not None and await session.get(
        AgentProfile, str(payload.agent_profile_id)
    ) is None:
        raise AgentProfileNotFoundError(str(payload.agent_profile_id))
    project.agent_profile_id = (
        str(payload.agent_profile_id) if payload.agent_profile_id else None
    )
    await session.commit()
    await session.refresh(project)
    return project
