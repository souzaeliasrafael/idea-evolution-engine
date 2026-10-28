from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.llm.dependencies import get_llm_router
from app.llm.router import LLMRouter
from app.schemas.development import (
    DevelopmentBlueprintCreate,
    DevelopmentBlueprintRead,
)
from app.services import development as development_service
from app.services import profiles as profile_service
from app.services.errors import (
    AgentExecutionFailedError,
    BudgetLimitReachedError,
    DevelopmentBlueprintAlreadyRunningError,
    ProjectNotFoundError,
    ProjectNotStructuredError,
)


router = APIRouter(tags=["development-blueprints"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
ModelRouter = Annotated[LLMRouter, Depends(get_llm_router)]


@router.get(
    "/projects/{project_id}/development-blueprints",
    response_model=list[DevelopmentBlueprintRead],
)
async def list_development_blueprints(
    project_id: UUID, session: DatabaseSession
) -> list[DevelopmentBlueprintRead]:
    try:
        return list(await development_service.list_blueprints(session, project_id))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post(
    "/projects/{project_id}/development-blueprints",
    response_model=DevelopmentBlueprintRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_development_blueprint(
    project_id: UUID,
    payload: DevelopmentBlueprintCreate,
    session: DatabaseSession,
    llm_router: ModelRouter,
) -> DevelopmentBlueprintRead:
    try:
        project_router = await profile_service.router_for_project(
            session, project_id, llm_router
        )
        return await development_service.generate_blueprint(
            session, project_id, project_router, payload
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectNotStructuredError as exc:
        raise HTTPException(
            status_code=409,
            detail="Project must have an evaluated concept before generating a blueprint",
        ) from exc
    except DevelopmentBlueprintAlreadyRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail="A development blueprint is already being generated",
        ) from exc
    except BudgetLimitReachedError as exc:
        raise HTTPException(
            status_code=409,
            detail="The project or blueprint AI budget was reached",
        ) from exc
    except AgentExecutionFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Development blueprint stopped: {exc}",
        ) from exc
