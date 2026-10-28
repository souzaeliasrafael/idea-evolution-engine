from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.llm.dependencies import get_llm_router
from app.llm.router import LLMRouter
from app.schemas.discovery import (
    CommercialValidationUpdate,
    DiscoveryAgentRunRead,
    DiscoveryCampaignCreate,
    DiscoveryCampaignRead,
    FounderProfileCreate,
    FounderProfileRead,
    FounderProfileUpdate,
    OpportunityCandidateRead,
    OpportunityFeedbackUpdate,
    OpportunityPromoteRequest,
    OpportunitySignalRead,
)
from app.schemas.project import ProjectRead
from app.services import discovery as discovery_service


router = APIRouter(tags=["opportunity-discovery"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
ModelRouter = Annotated[LLMRouter, Depends(get_llm_router)]


@router.post("/founder-profiles", response_model=FounderProfileRead, status_code=status.HTTP_201_CREATED)
async def create_founder_profile(payload: FounderProfileCreate, session: DatabaseSession):
    return await discovery_service.create_founder_profile(session, payload)


@router.get("/founder-profiles", response_model=list[FounderProfileRead])
async def list_founder_profiles(session: DatabaseSession):
    return list(await discovery_service.list_founder_profiles(session))


@router.put("/founder-profiles/{profile_id}", response_model=FounderProfileRead)
async def update_founder_profile(profile_id: UUID, payload: FounderProfileUpdate, session: DatabaseSession):
    try:
        return await discovery_service.update_founder_profile(session, profile_id, payload)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/discovery-campaigns", response_model=DiscoveryCampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: DiscoveryCampaignCreate, session: DatabaseSession):
    try:
        return await discovery_service.create_campaign(session, payload)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/discovery-campaigns", response_model=list[DiscoveryCampaignRead])
async def list_campaigns(session: DatabaseSession):
    return list(await discovery_service.list_campaigns(session))


@router.get("/discovery-campaigns/{campaign_id}", response_model=DiscoveryCampaignRead)
async def get_campaign(campaign_id: UUID, session: DatabaseSession):
    try:
        return await discovery_service.get_campaign(session, campaign_id)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/discovery-campaigns/{campaign_id}/run", response_model=DiscoveryCampaignRead)
async def run_campaign(campaign_id: UUID, session: DatabaseSession, model_router: ModelRouter):
    try:
        return await discovery_service.run_campaign(session, campaign_id, model_router)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except discovery_service.DiscoveryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/discovery-campaigns/{campaign_id}/cancel", response_model=DiscoveryCampaignRead)
async def cancel_campaign(campaign_id: UUID, session: DatabaseSession):
    try:
        return await discovery_service.cancel_campaign(session, campaign_id)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/discovery-campaigns/{campaign_id}/signals", response_model=list[OpportunitySignalRead])
async def list_signals(campaign_id: UUID, session: DatabaseSession):
    try:
        return list(await discovery_service.list_signals(session, campaign_id))
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/discovery-campaigns/{campaign_id}/opportunities", response_model=list[OpportunityCandidateRead])
async def list_candidates(campaign_id: UUID, session: DatabaseSession):
    try:
        return list(await discovery_service.list_candidates(session, campaign_id))
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/discovery-campaigns/{campaign_id}/runs", response_model=list[DiscoveryAgentRunRead])
async def list_runs(campaign_id: UUID, session: DatabaseSession):
    try:
        return list(await discovery_service.list_runs(session, campaign_id))
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/opportunities/{candidate_id}/promote", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def promote_candidate(candidate_id: UUID, payload: OpportunityPromoteRequest, session: DatabaseSession):
    try:
        return await discovery_service.promote_candidate(session, candidate_id, payload)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except discovery_service.DiscoveryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/opportunities/{candidate_id}/feedback", response_model=OpportunityCandidateRead)
async def update_candidate_feedback(
    candidate_id: UUID,
    payload: OpportunityFeedbackUpdate,
    session: DatabaseSession,
):
    try:
        return await discovery_service.update_candidate_feedback(session, candidate_id, payload)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/opportunities/{candidate_id}/commercial-validation", response_model=OpportunityCandidateRead)
async def update_commercial_validation(
    candidate_id: UUID,
    payload: CommercialValidationUpdate,
    session: DatabaseSession,
):
    try:
        return await discovery_service.update_commercial_validation(session, candidate_id, payload)
    except discovery_service.DiscoveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except discovery_service.DiscoveryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
