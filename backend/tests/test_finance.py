from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.base import BillingCostItem, BillingProviderAdapter
from app.billing.dependencies import get_billing_registry
from app.billing.openai import OpenAIBillingAdapter
from app.billing.registry import BillingRegistry
from app.database.models import AgentRun
from app.domain.enums import AgentType
from app.main import app


pytestmark = pytest.mark.anyio


class FakeBillingAdapter(BillingProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "future-ai"

    @property
    def configured(self) -> bool:
        return True

    async def fetch_costs(
        self, *, start: datetime, end: datetime
    ) -> list[BillingCostItem]:
        bucket_start = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        midpoint = bucket_start + timedelta(days=1)
        bucket_end = midpoint + timedelta(days=1)
        return [
            BillingCostItem(
                period_start=bucket_start,
                period_end=midpoint,
                amount=Decimal("1.25"),
                model="future-small",
                line_item="inference",
                external_project_id="external-project",
            ),
            BillingCostItem(
                period_start=midpoint,
                period_end=bucket_end,
                amount=Decimal("2.75"),
                model="future-large",
                line_item="reasoning",
                external_project_id="external-project",
            ),
        ]


async def test_overview_reports_estimates_tokens_and_project_budget(
    client: AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_response = await client.post(
        "/projects",
        json={
            "name": "Finance visibility",
            "raw_idea": "Measure every model call",
            "max_ai_budget": "10",
        },
    )
    project_id = project_response.json()["id"]
    async with session_maker() as session:
        session.add(
            AgentRun(
                project_id=project_id,
                agent=AgentType.BUILDER,
                provider="openai",
                model="gpt-test",
                prompt_version="builder-v1",
                input_json={},
                output_json={},
                input_tokens=120,
                output_tokens=30,
                cached_input_tokens=50,
                reasoning_tokens=10,
                estimated_cost=Decimal("0.0042"),
                execution_time=0.5,
            )
        )
        await session.commit()

    response = await client.get("/finance/overview?days=30")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["estimated_cost"] == "0.004200"
    assert Decimal(body["summary"]["reconciled_cost"]) == 0
    assert body["summary"]["cached_input_tokens"] == 50
    assert body["summary"]["reasoning_tokens"] == 10
    assert body["by_provider"][0]["provider"] == "openai"
    assert body["by_model"][0]["model"] == "gpt-test"
    assert body["by_model"][0]["reconciled_cost"] is None
    assert body["by_agent"][0]["agent"] == "BUILDER"
    project_row = next(item for item in body["by_project"] if item["project_id"] == project_id)
    assert project_row["max_ai_budget"] == "10.000000"


async def test_manual_cost_supports_any_provider(client: AsyncClient) -> None:
    start = datetime.now(UTC) - timedelta(days=1)
    response = await client.post(
        "/finance/costs/manual",
        json={
            "provider": "anthropic",
            "period_start": start.isoformat(),
            "period_end": (start + timedelta(hours=1)).isoformat(),
            "amount": "3.125",
            "currency": "USD",
            "model": "claude-future",
            "line_item": "messages",
            "note": "Imported from invoice",
        },
    )
    overview = await client.get("/finance/overview?days=7")

    assert response.status_code == 201
    assert response.json()["source"] == "MANUAL"
    assert overview.status_code == 200
    assert overview.json()["summary"]["reconciled_cost"] == "3.125000"
    assert overview.json()["by_provider"][0]["provider"] == "anthropic"


async def test_provider_sync_is_audited_and_idempotent(client: AsyncClient) -> None:
    registry = BillingRegistry()
    registry.register(FakeBillingAdapter())
    app.dependency_overrides[get_billing_registry] = lambda: registry

    first = await client.post("/finance/sync/future-ai", json={"days": 7})
    second = await client.post("/finance/sync/future-ai", json={"days": 7})
    overview = await client.get("/finance/overview?days=7")

    assert first.status_code == second.status_code == 200
    assert first.json()["entries_written"] == 2
    assert second.json()["status"] == "COMPLETED"
    body = overview.json()
    assert body["summary"]["reconciled_cost"] == "4.000000"
    assert len(body["recent_cost_entries"]) == 2
    assert len(body["recent_syncs"]) == 2
    assert body["connectors"][0]["provider"] == "future-ai"


async def test_openai_billing_adapter_handles_grouping_and_pagination() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer admin-secret"
        page = request.url.params.get("page")
        if page is None:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1_700_000_000,
                            "end_time": 1_700_086_400,
                            "results": [
                                {
                                    "object": "organization.costs.result",
                                    "amount": {"value": 1.5, "currency": "usd"},
                                    "line_item": "gpt-test, input",
                                    "project_id": "project-1",
                                    "api_key_id": "key-1",
                                }
                            ],
                        }
                    ],
                    "has_more": True,
                    "next_page": "next-token",
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "start_time": 1_700_086_400,
                        "end_time": 1_700_172_800,
                        "results": [
                            {
                                "amount": {"value": "2.25", "currency": "usd"},
                                "line_item": "storage",
                                "project_id": "project-1",
                            }
                        ],
                    }
                ],
                "has_more": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        adapter = OpenAIBillingAdapter(
            admin_key="admin-secret",
            base_url="https://api.openai.test/v1",
            timeout_seconds=10,
            project_ids=("project-1",),
            client=http_client,
        )
        items = await adapter.fetch_costs(
            start=datetime.fromtimestamp(1_700_000_000, tz=UTC),
            end=datetime.fromtimestamp(1_700_172_800, tz=UTC),
        )

    assert len(requests) == 2
    assert requests[0].url.path == "/v1/organization/costs"
    assert requests[0].url.params.get_list("group_by") == [
        "project_id",
        "api_key_id",
        "line_item",
    ]
    assert requests[0].url.params.get_list("project_ids") == ["project-1"]
    assert requests[1].url.params["page"] == "next-token"
    assert [item.amount for item in items] == [Decimal("1.5"), Decimal("2.25")]
    assert items[0].model == "gpt-test"


async def test_openai_billing_adapter_keeps_current_daily_bucket() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [], "has_more": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        adapter = OpenAIBillingAdapter(
            admin_key="admin-secret",
            base_url="https://api.openai.test/v1",
            timeout_seconds=10,
            client=http_client,
        )
        end = datetime.now(UTC)
        await adapter.fetch_costs(start=end - timedelta(days=7), end=end)

    assert len(requests) == 1
    assert "end_time" not in requests[0].url.params
