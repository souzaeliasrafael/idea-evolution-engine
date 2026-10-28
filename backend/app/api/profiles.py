from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.profiles import (
    AgentProfileCreate,
    AgentProfileRead,
    AgentProfileUpdate,
)
from app.services import profiles as profile_service
from app.services.errors import (
    AgentProfileAlreadyExistsError,
    AgentProfileInvalidError,
    AgentProfileNotFoundError,
)


router = APIRouter(prefix="/agent-profiles", tags=["agent-profiles"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", response_model=AgentProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: AgentProfileCreate, session: DatabaseSession
) -> AgentProfileRead:
    try:
        return await profile_service.create_profile(session, payload)
    except AgentProfileAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="Profile name already exists") from exc
    except AgentProfileInvalidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[AgentProfileRead])
async def list_profiles(session: DatabaseSession) -> list[AgentProfileRead]:
    return list(await profile_service.list_profiles(session))


@router.get("/{profile_id}", response_model=AgentProfileRead)
async def get_profile(profile_id: UUID, session: DatabaseSession) -> AgentProfileRead:
    try:
        return await profile_service.get_profile(session, profile_id)
    except AgentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc


@router.put("/{profile_id}", response_model=AgentProfileRead)
async def update_profile(
    profile_id: UUID, payload: AgentProfileUpdate, session: DatabaseSession
) -> AgentProfileRead:
    try:
        return await profile_service.update_profile(session, profile_id, payload)
    except AgentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc
    except AgentProfileAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="Profile name already exists") from exc
    except AgentProfileInvalidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: UUID, session: DatabaseSession) -> Response:
    try:
        await profile_service.delete_profile(session, profile_id)
    except AgentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
