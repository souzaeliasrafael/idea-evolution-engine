from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.providers.http import _SYSTEM_SSL_CONTEXT


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = BACKEND_ROOT / "work" / "http-cancellation-experiments"
TERMINAL_STATUSES = {"cancelled", "completed", "failed", "incomplete"}

LOAD_PROMPT = """Generate a numbered catalog of 500 distinct software failure
scenarios for a multi-agent AI workflow. For every item, write two complete
sentences: the failure mechanism and a concrete detection method. Continue in
order without summarizing, grouping, or stopping early."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a completed foreground Responses request with foreground "
            "connection termination and explicit background cancellation."
        )
    )
    parser.add_argument("--repetitions", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--model")
    parser.add_argument("--input-price-per-million", type=Decimal)
    parser.add_argument("--cached-input-price-per-million", type=Decimal)
    parser.add_argument("--output-price-per-million", type=Decimal)
    parser.add_argument("--cancel-after", type=float, default=1.0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--poll-seconds", type=float, default=20.0)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser.parse_args()


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _payload(*, model: str, max_output_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "instructions": "Follow the requested format exactly and be exhaustive.",
        "input": LOAD_PROMPT,
        "max_output_tokens": max_output_tokens,
        # Retrieval is required only so the experiment can observe what the server
        # did after the local HTTP connection was terminated.
        "store": True,
    }


def _decode(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("OpenAI returned a non-object response")
    return body


def _usage(body: dict[str, Any] | None) -> dict[str, int | bool]:
    value = body.get("usage") if body else None
    observed = isinstance(value, dict)
    value = value if observed else {}
    input_details = value.get("input_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = value.get("output_tokens_details")
    output_details = output_details if isinstance(output_details, dict) else {}

    def count(item: object) -> int:
        return max(0, int(item)) if isinstance(item, (int, float)) else 0

    return {
        "observed": observed,
        "input_tokens": count(value.get("input_tokens")),
        "cached_input_tokens": count(input_details.get("cached_tokens")),
        "output_tokens": count(value.get("output_tokens")),
        "reasoning_tokens": count(output_details.get("reasoning_tokens")),
        "total_tokens": count(value.get("total_tokens")),
    }


def _estimated_cost(
    usage: dict[str, int | bool],
    *,
    input_price: Decimal,
    cached_input_price: Decimal,
    output_price: Decimal,
) -> str | None:
    if not usage["observed"]:
        return None
    cached_tokens = min(
        int(usage["cached_input_tokens"]), int(usage["input_tokens"])
    )
    cost = (
        Decimal(int(usage["input_tokens"]) - cached_tokens) * input_price
        + Decimal(cached_tokens) * cached_input_price
        + Decimal(usage["output_tokens"]) * output_price
    ) / Decimal("1000000")
    return str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


async def _poll_response(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    response_id: str,
    poll_seconds: float,
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    deadline = perf_counter() + poll_seconds
    statuses: list[str] = []
    last: dict[str, Any] | None = None
    error: str | None = None
    while perf_counter() < deadline:
        response = await client.get(f"{url}/responses/{response_id}", headers=headers)
        if response.status_code == 404:
            error = "response_not_retrievable"
            break
        try:
            last = _decode(response)
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            break
        status = str(last.get("status") or "unknown")
        if not statuses or statuses[-1] != status:
            statuses.append(status)
        if status in TERMINAL_STATUSES:
            break
        await asyncio.sleep(0.5)
    if last and str(last.get("status")) not in TERMINAL_STATUSES and not error:
        error = "poll_timeout"
    return last, statuses, error


async def _foreground_complete(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    response = await client.post(f"{url}/responses", headers=headers, json=payload)
    body = _decode(response)
    return {
        "arm": "foreground_complete",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "response_id": body.get("id"),
        "status": body.get("status"),
        "status_history": [body.get("status")],
        "usage": _usage(body),
        "observation_error": None,
    }


async def _foreground_disconnect(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    cancel_after: float,
    poll_seconds: float,
) -> dict[str, Any]:
    del poll_seconds
    started = perf_counter()
    request_task = asyncio.create_task(
        client.post(f"{url}/responses", headers=headers, json=payload)
    )
    await asyncio.sleep(cancel_after)
    cancel_started = perf_counter()
    request_task.cancel()
    try:
        await request_task
        local_status = "completed_before_cancel"
    except asyncio.CancelledError:
        local_status = "connection_terminated"
    disconnect_elapsed = perf_counter() - cancel_started
    return {
        "arm": "foreground_disconnect",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "disconnect_elapsed_seconds": round(disconnect_elapsed, 3),
        "response_id": None,
        "status": local_status,
        "status_history": [local_status],
        "usage": _usage(None),
        "observation_error": (
            "Synchronous disconnection returns no final per-request usage; "
            "reconcile through the organization usage API."
        ),
    }


async def _background_cancel(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    cancel_after: float,
    poll_seconds: float,
) -> dict[str, Any]:
    started = perf_counter()
    create_response = await client.post(
        f"{url}/responses",
        headers=headers,
        json={**payload, "background": True},
    )
    created = _decode(create_response)
    response_id = str(created["id"])
    await asyncio.sleep(cancel_after)
    cancel_started = perf_counter()
    cancel_response = await client.post(
        f"{url}/responses/{response_id}/cancel", headers=headers
    )
    cancelled = _decode(cancel_response)
    cancel_elapsed = perf_counter() - cancel_started
    if str(cancelled.get("status")) in TERMINAL_STATUSES:
        body = cancelled
        statuses = [str(created.get("status")), str(cancelled.get("status"))]
        observation_error = None
    else:
        body, polled, observation_error = await _poll_response(
            client,
            url=url,
            headers=headers,
            response_id=response_id,
            poll_seconds=poll_seconds,
        )
        statuses = [str(created.get("status")), str(cancelled.get("status")), *polled]
    return {
        "arm": "background_cancel",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "cancel_api_elapsed_seconds": round(cancel_elapsed, 3),
        "response_id": response_id,
        "status": body.get("status") if body else None,
        "status_history": statuses,
        "usage": _usage(body),
        "observation_error": observation_error,
    }


def _summaries(results: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for arm in ("foreground_complete", "foreground_disconnect", "background_cancel"):
        members = [result for result in results if result["arm"] == arm]
        observed_costs = [
            float(result["estimated_cost_usd"])
            for result in members
            if result["estimated_cost_usd"] is not None
        ]
        observed_output = [
            int(result["usage"]["output_tokens"])
            for result in members
            if result["usage"]["observed"]
        ]
        summaries[arm] = {
            "runs": len(members),
            "terminal_statuses": [result["status"] for result in members],
            "mean_elapsed_seconds": round(
                mean(result["elapsed_seconds"] for result in members), 3
            ),
            "runs_with_observed_usage": len(observed_costs),
            "mean_output_tokens": (
                round(mean(observed_output), 1) if observed_output else None
            ),
            "mean_estimated_cost_usd": (
                round(mean(observed_costs), 6) if observed_costs else None
            ),
        }
    baseline = summaries["foreground_complete"]
    for arm in ("foreground_disconnect", "background_cancel"):
        current = summaries[arm]
        base_cost = baseline["mean_estimated_cost_usd"]
        base_tokens = baseline["mean_output_tokens"]
        current["estimated_cost_reduction_percent_vs_complete"] = (
            round(100 * (1 - current["mean_estimated_cost_usd"] / base_cost), 1)
            if base_cost is not None and current["mean_estimated_cost_usd"] is not None
            else None
        )
        current["output_token_reduction_percent_vs_complete"] = (
            round(100 * (1 - current["mean_output_tokens"] / base_tokens), 1)
            if base_tokens is not None and current["mean_output_tokens"] is not None
            else None
        )
    return summaries


async def run(args: argparse.Namespace) -> Path:
    settings = get_settings()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    api_key = settings.openai_api_key.get_secret_value()
    model = args.model or settings.llm_model
    input_price = args.input_price_per_million or settings.llm_input_cost_per_million
    cached_input_price = (
        args.cached_input_price_per_million
        or settings.llm_cached_input_cost_per_million
        or input_price
    )
    output_price = args.output_price_per_million or settings.llm_output_cost_per_million
    url = settings.openai_base_url.rstrip("/")
    headers = _headers(api_key)
    payload = _payload(model=model, max_output_tokens=args.max_output_tokens)
    results: list[dict[str, Any]] = []
    timeout = httpx.Timeout(max(settings.llm_request_timeout_seconds, 180.0))

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=_SYSTEM_SSL_CONTEXT,
    ) as client:
        for repetition in range(1, args.repetitions + 1):
            for operation in (
                _foreground_complete,
                _foreground_disconnect,
                _background_cancel,
            ):
                kwargs: dict[str, Any] = {
                    "client": client,
                    "url": url,
                    "headers": headers,
                    "payload": payload,
                }
                if operation is not _foreground_complete:
                    kwargs.update(
                        cancel_after=args.cancel_after,
                        poll_seconds=args.poll_seconds,
                    )
                result = await operation(**kwargs)
                result["repetition"] = repetition
                result["estimated_cost_usd"] = _estimated_cost(
                    result["usage"],
                    input_price=input_price,
                    cached_input_price=cached_input_price,
                    output_price=output_price,
                )
                results.append(result)
                print(
                    f"{operation.__name__} #{repetition}: "
                    f"status={result['status']} output={result['usage']['output_tokens']} "
                    f"cost=${result['estimated_cost_usd'] or 'unobserved'}"
                )

    report = {
        "experiment": "http-cancellation-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "model": model,
        "protocol": {
            "repetitions": args.repetitions,
            "cancel_after_seconds": args.cancel_after,
            "max_output_tokens": args.max_output_tokens,
            "foreground_disconnect": (
                "Cancel the asyncio task awaiting a synchronous foreground POST; "
                "httpx then closes the in-flight HTTP connection."
            ),
            "background_cancel": (
                "Create with background=true, then call POST /responses/{id}/cancel."
            ),
            "store": True,
            "production_store_setting": False,
        },
        "configured_price_assumption_usd_per_million": {
            "input": str(input_price),
            "cached_input": str(cached_input_price),
            "output": str(output_price),
            "warning": "This is the application's configured estimate, not a billing export.",
        },
        "results": results,
        "summary": _summaries(results),
        "known_experiment_estimated_cost_usd": str(
            sum(
                Decimal(result["estimated_cost_usd"])
                for result in results
                if result["estimated_cost_usd"] is not None
            )
        ),
        "limitations": [
            "Stored responses were enabled only to observe terminal status and usage.",
            "A small controlled prompt measures cancellation mechanics, not every model/load case.",
            "Cancelled requests may omit per-response usage and require organization usage reconciliation.",
            "Token cost is calculated with the application's configured prices.",
        ],
    }
    args.output_directory.mkdir(parents=True, exist_ok=True)
    path = args.output_directory / (
        f"http-cancellation-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    if args.cancel_after <= 0 or args.poll_seconds <= 0:
        raise SystemExit("cancel and poll durations must be positive")
    path = asyncio.run(run(args))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
