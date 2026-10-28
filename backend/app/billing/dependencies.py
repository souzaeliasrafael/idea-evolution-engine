from functools import lru_cache

from app.billing.base import BillingProviderAdapter
from app.billing.openai import OpenAIBillingAdapter
from app.billing.registry import BillingRegistry
from app.core.config import get_settings


@lru_cache
def get_billing_registry() -> BillingRegistry:
    settings = get_settings()
    registry = BillingRegistry()
    secret = settings.openai_admin_key
    getter = getattr(secret, "get_secret_value", None)
    admin_key = getter() if callable(getter) else None
    project_ids = tuple(
        item.strip()
        for item in settings.openai_billing_project_ids.split(",")
        if item.strip()
    )
    registry.register(
        OpenAIBillingAdapter(
            admin_key=admin_key,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            project_ids=project_ids,
        )
    )
    return registry


def register_billing_adapter(adapter: BillingProviderAdapter) -> None:
    """Register a provider billing adapter during application startup."""

    get_billing_registry().register(adapter)
