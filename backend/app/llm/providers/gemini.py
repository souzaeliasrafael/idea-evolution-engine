import json
from urllib.parse import quote

import httpx

from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.providers.http import HTTPJSONClient, TokenPricing, require_text


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        max_output_tokens: int,
        timeout_seconds: float,
        pricing: TokenPricing,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name.removeprefix("models/")
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
        model_path = quote(self.model_name, safe="")
        body = await self.http.post(
            f"/models/{model_path}:generateContent",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            payload={
                "systemInstruction": {"parts": [{"text": request.prompt}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": json.dumps(
                                    request.input_data, ensure_ascii=False
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": request.max_output_tokens or self.max_output_tokens,
                },
            },
            provider_name="Gemini",
        )
        fragments: list[str] = []
        candidates = body.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            content = candidate.get("content") if isinstance(candidate, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                fragments = [
                    part["text"]
                    for part in parts
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
        usage = (
            body.get("usageMetadata")
            if isinstance(body.get("usageMetadata"), dict)
            else {}
        )
        input_tokens = _nonnegative_int(usage.get("promptTokenCount"))
        output_tokens = _nonnegative_int(
            usage.get("candidatesTokenCount")
        ) + _nonnegative_int(usage.get("thoughtsTokenCount"))
        reasoning_tokens = _nonnegative_int(usage.get("thoughtsTokenCount"))
        cached_input_tokens = _nonnegative_int(
            usage.get("cachedContentTokenCount")
        )
        return LLMResponse(
            content=require_text("".join(fragments), "Gemini"),
            model=str(body.get("modelVersion") or self.model_name),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            estimated_cost=self.pricing.estimate(
                input_tokens, output_tokens, cached_input_tokens
            ),
        )


def _nonnegative_int(value: object) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0
