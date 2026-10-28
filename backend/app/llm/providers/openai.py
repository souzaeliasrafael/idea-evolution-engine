import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.llm.base import LLMProvider, LLMRequest, LLMResponse, WebSource
from app.llm.providers.http import HTTPJSONClient, TokenPricing, require_text


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        max_output_tokens: int,
        timeout_seconds: float,
        pricing: TokenPricing,
        web_search_cost_per_call: Decimal = Decimal("0.01"),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self.max_output_tokens = max_output_tokens
        self.pricing = pricing
        self.web_search_cost_per_call = web_search_cost_per_call
        self.http = HTTPJSONClient(
            base_url=base_url, timeout_seconds=timeout_seconds, client=client
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def supports_web_search(self) -> bool:
        return True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "instructions": request.prompt,
            "input": json.dumps(request.input_data, ensure_ascii=False),
            "max_output_tokens": request.max_output_tokens or self.max_output_tokens,
            "store": False,
        }
        if request.output_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.output_schema_name or "agent_output",
                    "strict": True,
                    "schema": request.output_schema,
                }
            }
        if request.web_search is not None:
            payload.update(
                {
                    "tools": [
                        {
                            "type": "web_search",
                            "search_context_size": request.web_search.context_size,
                        }
                    ],
                    "tool_choice": "required",
                    "max_tool_calls": request.web_search.max_calls,
                    "include": ["web_search_call.action.sources"],
                }
            )
        body = await self.http.post(
            "/responses",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            provider_name="OpenAI",
        )
        content = body.get("output_text") or _extract_output_text(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_tokens = _nonnegative_int(usage.get("input_tokens"))
        output_tokens = _nonnegative_int(usage.get("output_tokens"))
        input_details = (
            usage.get("input_tokens_details")
            if isinstance(usage.get("input_tokens_details"), dict)
            else {}
        )
        output_details = (
            usage.get("output_tokens_details")
            if isinstance(usage.get("output_tokens_details"), dict)
            else {}
        )
        cached_input_tokens = _nonnegative_int(input_details.get("cached_tokens"))
        finish_reason = _finish_reason(body, content)
        web_search_calls, web_sources = _web_search_metadata(body)
        tool_cost = (
            self.web_search_cost_per_call * Decimal(web_search_calls)
        ).quantize(Decimal("0.000001"))
        return LLMResponse(
            content=(
                str(content)
                if finish_reason is not None
                else require_text(content, "OpenAI")
            ),
            model=str(body.get("model") or self.model_name),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=_nonnegative_int(output_details.get("reasoning_tokens")),
            web_search_calls=web_search_calls,
            tool_cost=tool_cost,
            web_sources=web_sources,
            estimated_cost=(
                self.pricing.estimate(
                    input_tokens, output_tokens, cached_input_tokens
                ) + tool_cost
            ),
            finish_reason=finish_reason,
        )


def _extract_output_text(body: dict[str, Any]) -> str:
    fragments: list[str] = []
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("content"), list):
            continue
        for part in item["content"]:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                fragments.append(part["text"])
    return "".join(fragments)


def _nonnegative_int(value: object) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


def _finish_reason(body: dict[str, Any], content: object) -> str | None:
    status = body.get("status")
    if status == "incomplete":
        details = body.get("incomplete_details")
        if isinstance(details, dict) and isinstance(details.get("reason"), str):
            return str(details["reason"])
        return "incomplete"
    if status in {"failed", "cancelled"}:
        return str(status)
    if status == "completed" and (not isinstance(content, str) or not content.strip()):
        return "no_text_output"
    return None


def _web_search_metadata(body: dict[str, Any]) -> tuple[int, tuple[WebSource, ...]]:
    output = body.get("output")
    if not isinstance(output, list):
        return 0, ()

    web_search_calls = 0
    sources: dict[str, str] = {}
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            web_search_calls += 1
            action = item.get("action")
            if isinstance(action, dict) and isinstance(action.get("sources"), list):
                for source in action["sources"]:
                    _add_source(sources, source)
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or not isinstance(
                part.get("annotations"), list
            ):
                continue
            for annotation in part["annotations"]:
                if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                    _add_source(sources, annotation)

    return web_search_calls, tuple(
        WebSource(url=url, title=title) for url, title in list(sources.items())[:50]
    )


def _add_source(sources: dict[str, str], source: object) -> None:
    if not isinstance(source, dict) or not isinstance(source.get("url"), str):
        return
    url = source["url"].strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return
    title = source.get("title") if isinstance(source.get("title"), str) else ""
    title = title.strip()
    if url not in sources or (not sources[url] and title):
        sources[url] = title
