from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.dependencies import get_billing_registry
from app.billing.registry import BillingProviderNotFoundError, BillingRegistry
from app.database.session import get_db_session
from app.schemas.finance import (
    BillingSyncRead,
    FinanceOverviewRead,
    FinanceSyncRequest,
    ManualCostCreate,
    ProviderCostEntryRead,
)
from app.services import finance
from app.services.errors import BillingSyncError


router = APIRouter(prefix="/finance", tags=["finance"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
BillingAdapters = Annotated[BillingRegistry, Depends(get_billing_registry)]


@router.get("/overview", response_model=FinanceOverviewRead)
async def financial_overview(
    session: DatabaseSession,
    registry: BillingAdapters,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> FinanceOverviewRead:
    return await finance.overview(session, registry, days=days)


@router.post("/sync/{provider}", response_model=BillingSyncRead)
async def sync_provider_costs(
    provider: str,
    payload: FinanceSyncRequest,
    session: DatabaseSession,
    registry: BillingAdapters,
) -> BillingSyncRead:
    try:
        return await finance.sync_provider(
            session, registry, provider, days=payload.days
        )
    except BillingProviderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este provedor ainda não possui um adaptador financeiro.",
        ) from exc
    except BillingSyncError as exc:
        message = str(exc)
        http_status = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if "_KEY" in message or "required" in message.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=http_status, detail=message) from exc


@router.post(
    "/costs/manual",
    response_model=ProviderCostEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_cost(
    payload: ManualCostCreate, session: DatabaseSession
) -> ProviderCostEntryRead:
    return await finance.add_manual_cost(session, payload)
