from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.base import BillingCostItem
from app.billing.registry import BillingRegistry
from app.database.models import AgentRun, BillingSync, Project, ProviderCostEntry, utc_now
from app.domain.enums import BillingCostSource, BillingSyncStatus
from app.schemas.finance import (
    AgentFinanceRead,
    BillingConnectorRead,
    BillingSyncRead,
    DailyFinanceRead,
    FinanceOverviewRead,
    FinanceSummaryRead,
    ManualCostCreate,
    ModelFinanceRead,
    ProjectFinanceRead,
    ProviderCostEntryRead,
    ProviderFinanceRead,
)
from app.services.errors import BillingSyncError


ZERO = Decimal("0")
ItemT = TypeVar("ItemT")
KeyT = TypeVar("KeyT", bound=Hashable)
LOCAL_PROVIDERS = {
    "mock",
    "local",
    "compatible",
    "openai-compatible",
    "openai_compatible",
}


async def overview(
    session: AsyncSession,
    registry: BillingRegistry,
    *,
    days: int,
) -> FinanceOverviewRead:
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=days)
    runs = list(
        (
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.created_at >= period_start)
                .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            )
        ).all()
    )
    projects = list(
        (
            await session.scalars(
                select(Project).order_by(Project.created_at.asc(), Project.id.asc())
            )
        ).all()
    )
    entries = list(
        (
            await session.scalars(
                select(ProviderCostEntry)
                .where(
                    ProviderCostEntry.period_end > period_start,
                    ProviderCostEntry.period_start < period_end,
                )
                .order_by(ProviderCostEntry.period_start.desc())
            )
        ).all()
    )
    syncs = list(
        (
            await session.scalars(
                select(BillingSync)
                .order_by(BillingSync.started_at.desc(), BillingSync.id.desc())
                .limit(20)
            )
        ).all()
    )

    usd_entries = [entry for entry in entries if entry.currency.upper() == "USD"]
    estimated = _sum(run.estimated_cost for run in runs)
    reconciled = _sum(entry.amount for entry in usd_entries)
    period_run_groups = _group(runs, lambda run: run.project_id)
    provider_runs = _group(runs, lambda run: run.provider.lower())
    provider_entries = _group(usd_entries, lambda entry: entry.provider.lower())
    model_runs = _group(runs, lambda run: (run.provider.lower(), run.model))
    model_entries = _group(
        [entry for entry in usd_entries if entry.model],
        lambda entry: (entry.provider.lower(), str(entry.model)),
    )
    agent_runs = _group(runs, lambda run: run.agent)
    connector_map = {
        adapter.provider_name: adapter for adapter in registry.list()
    }
    latest_sync = _latest_sync_by_provider(syncs)

    provider_names = sorted(
        set(provider_runs) | set(provider_entries) | set(connector_map)
    )
    by_provider = []
    for provider in provider_names:
        provider_run_items = provider_runs.get(provider, [])
        provider_cost_items = provider_entries.get(provider, [])
        estimated_cost = _sum(item.estimated_cost for item in provider_run_items)
        reconciled_cost = _sum(item.amount for item in provider_cost_items)
        last_sync = latest_sync.get(provider)
        by_provider.append(
            ProviderFinanceRead(
                provider=provider,
                estimated_cost=estimated_cost,
                reconciled_cost=reconciled_cost,
                variance=reconciled_cost - estimated_cost,
                runs=len(provider_run_items),
                input_tokens=sum(item.input_tokens for item in provider_run_items),
                output_tokens=sum(item.output_tokens for item in provider_run_items),
                web_search_calls=sum(
                    item.web_search_calls for item in provider_run_items
                ),
                tool_cost=_sum(item.tool_cost for item in provider_run_items),
                models=sorted({item.model for item in provider_run_items}),
                connector_configured=(
                    connector_map[provider].configured if provider in connector_map else False
                ),
                last_synced_at=last_sync.completed_at if last_sync else None,
            )
        )

    model_keys = sorted(set(model_runs) | set(model_entries))
    by_model = [
        ModelFinanceRead(
            provider=provider,
            model=model,
            runs=len(model_runs.get((provider, model), [])),
            input_tokens=sum(
                item.input_tokens for item in model_runs.get((provider, model), [])
            ),
            output_tokens=sum(
                item.output_tokens for item in model_runs.get((provider, model), [])
            ),
            cached_input_tokens=sum(
                item.cached_input_tokens
                for item in model_runs.get((provider, model), [])
            ),
            reasoning_tokens=sum(
                item.reasoning_tokens for item in model_runs.get((provider, model), [])
            ),
            web_search_calls=sum(
                item.web_search_calls
                for item in model_runs.get((provider, model), [])
            ),
            tool_cost=_sum(
                item.tool_cost for item in model_runs.get((provider, model), [])
            ),
            estimated_cost=_sum(
                item.estimated_cost for item in model_runs.get((provider, model), [])
            ),
            reconciled_cost=(
                _sum(item.amount for item in model_entries[(provider, model)])
                if (provider, model) in model_entries
                else None
            ),
        )
        for provider, model in model_keys
    ]

    by_agent = [
        AgentFinanceRead(
            agent=agent,
            runs=len(items),
            input_tokens=sum(item.input_tokens for item in items),
            output_tokens=sum(item.output_tokens for item in items),
            web_search_calls=sum(item.web_search_calls for item in items),
            tool_cost=_sum(item.tool_cost for item in items),
            estimated_cost=_sum(item.estimated_cost for item in items),
        )
        for agent, items in sorted(agent_runs.items(), key=lambda item: item[0].value)
    ]
    by_project = [
        ProjectFinanceRead(
            project_id=project.id,
            name=project.name,
            status=project.status,
            runs=len(period_run_groups.get(project.id, [])),
            period_estimated_cost=_sum(
                item.estimated_cost for item in period_run_groups.get(project.id, [])
            ),
            all_time_estimated_cost=project.total_cost,
            max_ai_budget=project.max_ai_budget,
            remaining_ai_budget=project.remaining_ai_budget,
            budget_exhausted=project.budget_exhausted,
        )
        for project in projects
    ]
    daily = _daily(period_start, period_end, runs, usd_entries)
    connectors = []
    for adapter in registry.list():
        last_sync = latest_sync.get(adapter.provider_name)
        if not adapter.configured:
            guidance = "Configure a credencial administrativa no backend."
        elif (
            last_sync is not None
            and last_sync.status == BillingSyncStatus.COMPLETED
            and last_sync.entries_seen == 0
        ):
            guidance = (
                "A última sincronização não encontrou custos disponíveis. "
                "O provedor pode ainda estar processando o faturamento; tente novamente."
            )
        else:
            guidance = "Conector pronto para sincronizar custos faturados."
        connectors.append(
            BillingConnectorRead(
                provider=adapter.provider_name,
                configured=adapter.configured,
                supports_sync=True,
                last_sync_status=last_sync.status if last_sync else None,
                last_synced_at=last_sync.completed_at if last_sync else None,
                guidance=guidance,
            )
        )

    return FinanceOverviewRead(
        generated_at=period_end,
        period_start=period_start,
        period_end=period_end,
        summary=FinanceSummaryRead(
            estimated_cost=estimated,
            reconciled_cost=reconciled,
            variance=reconciled - estimated,
            all_time_estimated_cost=_sum(project.total_cost for project in projects),
            configured_budget=_sum(
                project.max_ai_budget
                for project in projects
                if project.max_ai_budget is not None
            ),
            total_runs=len(runs),
            input_tokens=sum(run.input_tokens for run in runs),
            output_tokens=sum(run.output_tokens for run in runs),
            cached_input_tokens=sum(run.cached_input_tokens for run in runs),
            reasoning_tokens=sum(run.reasoning_tokens for run in runs),
            web_search_calls=sum(run.web_search_calls for run in runs),
            tool_cost=_sum(run.tool_cost for run in runs),
            projects_at_or_over_budget=sum(project.budget_exhausted for project in projects),
            unpriced_runs=sum(
                run.provider.lower() not in LOCAL_PROVIDERS
                and run.input_tokens + run.output_tokens > 0
                and run.estimated_cost == 0
                for run in runs
            ),
            unsupported_currency_entries=len(entries) - len(usd_entries),
        ),
        by_provider=by_provider,
        by_model=by_model,
        by_agent=by_agent,
        by_project=by_project,
        daily=daily,
        connectors=connectors,
        recent_cost_entries=[
            ProviderCostEntryRead.model_validate(entry) for entry in entries[:50]
        ],
        recent_syncs=[BillingSyncRead.model_validate(item) for item in syncs],
    )


async def add_manual_cost(
    session: AsyncSession, payload: ManualCostCreate
) -> ProviderCostEntry:
    now = utc_now()
    entry = ProviderCostEntry(
        external_reference=sha256(f"manual:{uuid4()}".encode()).hexdigest(),
        provider=payload.provider.lower(),
        source=BillingCostSource.MANUAL,
        period_start=payload.period_start,
        period_end=payload.period_end,
        amount=payload.amount,
        currency=payload.currency,
        model=payload.model,
        line_item=payload.line_item,
        details={"note": payload.note} if payload.note else {},
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def sync_provider(
    session: AsyncSession,
    registry: BillingRegistry,
    provider: str,
    *,
    days: int,
) -> BillingSync:
    adapter = registry.get(provider)
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=days)
    started_at = utc_now()
    try:
        items = await adapter.fetch_costs(start=period_start, end=period_end)
        for item in items:
            await _upsert_provider_cost(session, adapter.provider_name, item)
        sync = BillingSync(
            provider=adapter.provider_name,
            status=BillingSyncStatus.COMPLETED,
            period_start=period_start,
            period_end=period_end,
            entries_seen=len(items),
            entries_written=len(items),
            started_at=started_at,
            completed_at=utc_now(),
        )
        session.add(sync)
        await session.commit()
        await session.refresh(sync)
        return sync
    except Exception as exc:
        await session.rollback()
        sync = BillingSync(
            provider=adapter.provider_name,
            status=BillingSyncStatus.FAILED,
            period_start=period_start,
            period_end=period_end,
            entries_seen=0,
            entries_written=0,
            error=f"{type(exc).__name__}: {exc}"[:2000],
            started_at=started_at,
            completed_at=utc_now(),
        )
        session.add(sync)
        await session.commit()
        raise BillingSyncError(str(exc)) from exc


async def _upsert_provider_cost(
    session: AsyncSession, provider: str, item: BillingCostItem
) -> None:
    reference = _external_reference(provider, item)
    entry = await session.scalar(
        select(ProviderCostEntry).where(
            ProviderCostEntry.external_reference == reference
        )
    )
    if entry is None:
        entry = ProviderCostEntry(external_reference=reference)
        session.add(entry)
    entry.provider = provider
    entry.source = BillingCostSource.PROVIDER_API
    entry.period_start = item.period_start
    entry.period_end = item.period_end
    entry.amount = item.amount
    entry.currency = item.currency.upper()
    entry.model = item.model
    entry.line_item = item.line_item
    entry.external_project_id = item.external_project_id
    entry.external_api_key_id = item.external_api_key_id
    entry.quantity = item.quantity
    entry.quantity_unit = item.quantity_unit
    entry.details = item.details
    entry.updated_at = utc_now()


def _external_reference(provider: str, item: BillingCostItem) -> str:
    natural_key = json.dumps(
        {
            "provider": provider,
            "period_start": item.period_start.isoformat(),
            "period_end": item.period_end.isoformat(),
            "currency": item.currency,
            "model": item.model,
            "line_item": item.line_item,
            "project": item.external_project_id,
            "api_key": item.external_api_key_id,
            "quantity_unit": item.quantity_unit,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(natural_key.encode()).hexdigest()


def _daily(
    start: datetime,
    end: datetime,
    runs: list[AgentRun],
    entries: list[ProviderCostEntry],
) -> list[DailyFinanceRead]:
    estimated: dict[str, Decimal] = defaultdict(lambda: ZERO)
    reconciled: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for run in runs:
        estimated[run.created_at.date().isoformat()] += run.estimated_cost
    for entry in entries:
        reconciled[entry.period_start.date().isoformat()] += entry.amount
    result = []
    current = start.date()
    while current <= end.date():
        key = current.isoformat()
        result.append(
            DailyFinanceRead(
                date=key,
                estimated_cost=estimated[key],
                reconciled_cost=reconciled[key],
            )
        )
        current += timedelta(days=1)
    return result


def _latest_sync_by_provider(syncs: list[BillingSync]) -> dict[str, BillingSync]:
    latest: dict[str, BillingSync] = {}
    for item in syncs:
        latest.setdefault(item.provider.lower(), item)
    return latest


def _group(
    items: Iterable[ItemT], key: Callable[[ItemT], KeyT]
) -> dict[KeyT, list[ItemT]]:
    groups: dict[KeyT, list[ItemT]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return groups


def _sum(values: Iterable[Decimal]) -> Decimal:
    return sum(values, ZERO)
