import json

import httpx

from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.providers.http import HTTPJSONClient, TokenPricing, require_text


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str | None,
        max_output_tokens: int,
        timeout_seconds: float,
        pricing: TokenPricing,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self.max_output_tokens = max_output_tokens
        self.pricing = pricing
        self.http = HTTPJSONClient(
            base_url=base_url, timeout_seconds=timeout_seconds, client=client
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = await self.http.post(
            "/chat/completions",
            headers=headers,
            payload={
                "model": self.model_name,
                "max_tokens": request.max_output_tokens or self.max_output_tokens,
                "messages": [
                    {"role": "system", "content": request.prompt},
                    {
                        "role": "user",
                        "content": json.dumps(request.input_data, ensure_ascii=False),
                    },
                ],
            },
            provider_name="OpenAI-compatible provider",
        )
        content: object = None
        choices = body.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_tokens = _nonnegative_int(usage.get("prompt_tokens"))
        output_tokens = _nonnegative_int(usage.get("completion_tokens"))
        input_details = (
            usage.get("prompt_tokens_details")
            if isinstance(usage.get("prompt_tokens_details"), dict)
            else {}
        )
        output_details = (
            usage.get("completion_tokens_details")
            if isinstance(usage.get("completion_tokens_details"), dict)
            else {}
        )
        cached_input_tokens = _nonnegative_int(input_details.get("cached_tokens"))
        return LLMResponse(
            content=require_text(content, "OpenAI-compatible provider"),
            model=str(body.get("model") or self.model_name),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=_nonnegative_int(output_details.get("reasoning_tokens")),
            estimated_cost=self.pricing.estimate(
                input_tokens, output_tokens, cached_input_tokens
            ),
        )


def _nonnegative_int(value: object) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0
