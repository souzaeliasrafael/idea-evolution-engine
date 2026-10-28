from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.domain.enums import AgentType
from app.schemas.prompts import (
    AgentPromptRead,
    AgentPromptUpdate,
    AgentPromptVersionRead,
)
from app.services import prompts as prompt_service


router = APIRouter(prefix="/agent-prompts", tags=["agent-prompts"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=list[AgentPromptRead])
async def list_prompts(session: DatabaseSession) -> list[AgentPromptRead]:
    return await prompt_service.list_prompt_configurations(session)


@router.get(
    "/{agent}/versions", response_model=list[AgentPromptVersionRead]
)
async def list_prompt_versions(
    agent: AgentType, session: DatabaseSession
) -> list[AgentPromptVersionRead]:
    return list(await prompt_service.list_prompt_versions(session, agent))


@router.put("/{agent}", response_model=AgentPromptRead)
async def update_prompt(
    agent: AgentType,
    payload: AgentPromptUpdate,
    session: DatabaseSession,
) -> AgentPromptRead:
    return await prompt_service.create_prompt_version(session, agent, payload)


@router.delete("/{agent}", response_model=AgentPromptRead)
async def reset_prompt(
    agent: AgentType, session: DatabaseSession
) -> AgentPromptRead:
    return await prompt_service.reset_prompt(session, agent)
