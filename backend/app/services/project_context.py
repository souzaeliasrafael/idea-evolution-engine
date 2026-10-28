from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import IdeaVersion, Project
from app.services.budget import refresh_budget
from app.services.errors import ProjectNotFoundError, ProjectNotStructuredError


async def get_project_and_latest_version(
    session: AsyncSession, project_id: UUID
) -> tuple[Project, IdeaVersion]:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    await refresh_budget(session, project)

    current_version = await session.scalar(
        select(IdeaVersion)
        .where(IdeaVersion.project_id == project.id)
        .order_by(IdeaVersion.version.desc())
        .limit(1)
    )
    if current_version is None:
        raise ProjectNotStructuredError(project.id)
    return project, current_version
