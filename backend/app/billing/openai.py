from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.billing.base import (
    BillingConfigurationError,
    BillingCostItem,
    BillingProviderAdapter,
)
from app.llm.providers.http import HTTPJSONClient


class OpenAIBillingAdapter(BillingProviderAdapter):
    def __init__(
        self,
        *,
        admin_key: str | None,
        base_url: str,
        timeout_seconds: float,
        project_ids: tuple[str, ...] = (),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._admin_key = admin_key.strip() if admin_key else None
        self._project_ids = tuple(item for item in project_ids if item)
        self.http = HTTPJSONClient(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            client=client,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def configured(self) -> bool:
        return bool(self._admin_key)

    async def fetch_costs(
        self, *, start: datetime, end: datetime
    ) -> list[BillingCostItem]:
        if not self._admin_key:
            raise BillingConfigurationError(
                "OPENAI_ADMIN_KEY is required for OpenAI cost reconciliation"
            )
        items: list[BillingCostItem] = []
        page: str | None = None
        while True:
            params = [
                ("start_time", str(int(start.timestamp()))),
                ("bucket_width", "1d"),
                ("limit", "180"),
                ("group_by", "project_id"),
                ("group_by", "api_key_id"),
                ("group_by", "line_item"),
            ]
            # The Costs API aggregates in daily buckets. Sending an end_time
            # inside the current UTC bucket can omit that whole bucket and make
            # a successful sync look empty. The endpoint's optional end_time
            # naturally defaults to the current reporting boundary, which is
            # exactly what an up-to-now reconciliation needs.
            if end.astimezone(UTC).date() < datetime.now(UTC).date():
                params.insert(1, ("end_time", str(int(end.timestamp()))))
            params.extend(("project_ids", project_id) for project_id in self._project_ids)
            if page:
                params.append(("page", page))
            body = await self.http.get(
                "/organization/costs",
                headers={
                    "Authorization": f"Bearer {self._admin_key}",
                    "Content-Type": "application/json",
                },
                params=params,
                provider_name="OpenAI billing",
            )
            buckets = body.get("data")
            if not isinstance(buckets, list):
                raise ValueError("OpenAI billing returned an invalid data list")
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                bucket_start = _timestamp(bucket.get("start_time"))
                bucket_end = _timestamp(bucket.get("end_time"))
                results = bucket.get("results")
                if not isinstance(results, list):
                    continue
                for result in results:
                    item = _cost_item(result, bucket_start, bucket_end)
                    if item is not None:
                        items.append(item)
            if not body.get("has_more"):
                break
            next_page = body.get("next_page")
            if not isinstance(next_page, str) or not next_page:
                raise ValueError("OpenAI billing pagination did not return next_page")
            page = next_page
        return items


def _cost_item(
    result: object, period_start: datetime, period_end: datetime
) -> BillingCostItem | None:
    if not isinstance(result, dict):
        return None
    amount_object = result.get("amount")
    if not isinstance(amount_object, dict):
        return None
    try:
        amount = Decimal(str(amount_object.get("value")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    line_item = _optional_text(result.get("line_item"))
    model = line_item.split(",", 1)[0].strip() if line_item and "," in line_item else None
    return BillingCostItem(
        period_start=period_start,
        period_end=period_end,
        amount=amount,
        currency=str(amount_object.get("currency") or "usd").upper(),
        model=model or None,
        line_item=line_item,
        external_project_id=_optional_text(result.get("project_id")),
        external_api_key_id=_optional_text(result.get("api_key_id")),
        quantity=_optional_decimal(result.get("quantity")),
        quantity_unit=_optional_text(result.get("quantity_unit")),
        details={"object": result.get("object")},
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, (int, float)):
        raise ValueError("OpenAI billing bucket is missing a timestamp")
    return datetime.fromtimestamp(value, tz=UTC)


def _optional_text(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
