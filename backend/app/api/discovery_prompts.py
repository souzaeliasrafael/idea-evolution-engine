from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.domain.enums import DiscoveryAgentType
from app.schemas.discovery import DiscoveryPromptRead, DiscoveryPromptUpdate, DiscoveryPromptVersionRead
from app.services import discovery_prompts as prompt_service


router = APIRouter(prefix="/discovery-prompts", tags=["discovery-prompts"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=list[DiscoveryPromptRead])
async def list_prompts(session: DatabaseSession):
    return await prompt_service.list_configurations(session)


@router.get("/{agent}/versions", response_model=list[DiscoveryPromptVersionRead])
async def list_versions(agent: DiscoveryAgentType, session: DatabaseSession):
    return list(await prompt_service.list_versions(session, agent))


@router.put("/{agent}", response_model=DiscoveryPromptRead)
async def update_prompt(agent: DiscoveryAgentType, payload: DiscoveryPromptUpdate, session: DatabaseSession):
    return await prompt_service.create_version(session, agent, payload)


@router.delete("/{agent}", response_model=DiscoveryPromptRead)
async def reset_prompt(agent: DiscoveryAgentType, session: DatabaseSession):
    return await prompt_service.reset(session, agent)
