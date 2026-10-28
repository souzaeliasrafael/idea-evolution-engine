from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import ssl
from typing import Any

import httpx
import truststore


class ProviderConfigurationError(ValueError):
    pass


class ProviderRequestError(RuntimeError):
    pass


_SYSTEM_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


@dataclass(frozen=True)
class TokenPricing:
    input_per_million: Decimal = Decimal("0")
    cached_input_per_million: Decimal | None = None
    output_per_million: Decimal = Decimal("0")

    def estimate(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Decimal:
        cached_tokens = min(max(cached_input_tokens, 0), max(input_tokens, 0))
        uncached_tokens = max(input_tokens - cached_tokens, 0)
        cached_rate = (
            self.cached_input_per_million
            if self.cached_input_per_million is not None
            else self.input_per_million
        )
        raw = (
            Decimal(uncached_tokens) * self.input_per_million
            + Decimal(cached_tokens) * cached_rate
            + Decimal(output_tokens) * self.output_per_million
        ) / Decimal("1000000")
        return raw.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class HTTPJSONClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ProviderConfigurationError("Provider base URL cannot be blank")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            if self.client is not None:
                response = await self.client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    verify=_SYSTEM_SSL_CONTEXT,
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                f"{provider_name} request failed: {type(exc).__name__}"
            ) from exc
        return self._decode(response, provider_name)

    async def get(
        self,
        path: str,
        *,
        headers: dict[str, str],
        params: list[tuple[str, str]],
        provider_name: str,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            if self.client is not None:
                response = await self.client.get(url, headers=headers, params=params)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    verify=_SYSTEM_SSL_CONTEXT,
                ) as client:
                    response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                f"{provider_name} request failed: {type(exc).__name__}"
            ) from exc
        return self._decode(response, provider_name)

    @staticmethod
    def _decode(response: httpx.Response, provider_name: str) -> dict[str, Any]:
        if not response.is_success:
            detail = response.text.replace("\n", " ")[:500]
            raise ProviderRequestError(
                f"{provider_name} returned HTTP {response.status_code}: {detail}"
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                f"{provider_name} returned a non-JSON response"
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderRequestError(
                f"{provider_name} returned an invalid response object"
            )
        return decoded


def require_api_key(value: str | None, environment_name: str) -> str:
    if value is None or not value.strip():
        raise ProviderConfigurationError(
            f"{environment_name} is required for the selected provider"
        )
    return value


def require_text(value: object, provider_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderRequestError(f"{provider_name} returned no text output")
    return value
