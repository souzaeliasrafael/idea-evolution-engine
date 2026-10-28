from app.billing.base import BillingProviderAdapter


class BillingProviderNotFoundError(LookupError):
    pass


class BillingRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, BillingProviderAdapter] = {}

    def register(self, adapter: BillingProviderAdapter) -> None:
        name = adapter.provider_name.strip().lower()
        if not name:
            raise ValueError("Billing provider name cannot be blank")
        if name in self._adapters:
            raise ValueError(f"Billing adapter is already registered: {name}")
        self._adapters[name] = adapter

    def get(self, provider: str) -> BillingProviderAdapter:
        normalized = provider.strip().lower()
        adapter = self._adapters.get(normalized)
        if adapter is None:
            raise BillingProviderNotFoundError(normalized)
        return adapter

    def list(self) -> list[BillingProviderAdapter]:
        return [self._adapters[name] for name in sorted(self._adapters)]
