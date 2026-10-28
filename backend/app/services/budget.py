from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Project
from app.services.errors import BudgetLimitReachedError


def require_budget_available(project: Project) -> None:
    """Prevent a new LLM call after a configured project budget is exhausted."""

    if project.budget_exhausted:
        raise BudgetLimitReachedError(project.id)


async def refresh_budget(session: AsyncSession, project: Project) -> None:
    """Reload mutable budget fields before starting another provider call."""

    await session.refresh(
        project,
        attribute_names=["max_ai_budget", "total_cost"],
    )
