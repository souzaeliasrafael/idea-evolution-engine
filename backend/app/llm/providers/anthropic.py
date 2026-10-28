import json

import httpx

from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.providers.http import HTTPJSONClient, TokenPricing, require_text


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        api_version: str,
        max_output_tokens: int,
        timeout_seconds: float,
        pricing: TokenPricing,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self.api_version = api_version
        self.max_output_tokens = max_output_tokens
        self.pricing = pricing
        self.http = HTTPJSONClient(
            base_url=base_url, timeout_seconds=timeout_seconds, client=client
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        body = await self.http.post(
            "/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self.api_version,
                "Content-Type": "application/json",
            },
            payload={
                "model": self.model_name,
                "max_tokens": request.max_output_tokens or self.max_output_tokens,
                "system": request.prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(request.input_data, ensure_ascii=False),
                    }
                ],
            },
            provider_name="Anthropic",
        )
        fragments = [
            part["text"]
            for part in body.get("content", [])
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ] if isinstance(body.get("content"), list) else []
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        cached_input_tokens = _nonnegative_int(usage.get("cache_read_input_tokens"))
        input_tokens = (
            _nonnegative_int(usage.get("input_tokens"))
            + _nonnegative_int(usage.get("cache_creation_input_tokens"))
            + cached_input_tokens
        )
        output_tokens = _nonnegative_int(usage.get("output_tokens"))
        return LLMResponse(
            content=require_text("".join(fragments), "Anthropic"),
            model=str(body.get("model") or self.model_name),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            estimated_cost=self.pricing.estimate(
                input_tokens, output_tokens, cached_input_tokens
            ),
        )


def _nonnegative_int(value: object) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0
