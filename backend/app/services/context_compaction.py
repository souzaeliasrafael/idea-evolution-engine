from __future__ import annotations

from typing import Any


def compact_text(value: str, *, limit: int = 600) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}… [truncated {len(value) - limit} chars]"


def compact_records(
    records: list[dict[str, Any]],
    *,
    limit: int,
    text_limit: int = 500,
) -> list[dict[str, Any]]:
    """Build a deterministic, bounded summary of the most relevant records."""
    effective_limit = min(limit, 12)
    return [
        _compact_value(item, text_limit=text_limit, list_limit=8, depth=0)
        for item in records[:effective_limit]
    ]


def compact_concept(concept: dict[str, Any]) -> dict[str, Any]:
    """Bound every concept field, including the immutable raw idea."""

    compacted = _compact_value(concept, text_limit=1200, list_limit=8, depth=0)
    return compacted if isinstance(compacted, dict) else {}


def compact_accumulated_context(
    context: dict[str, Any] | None,
    *,
    max_events: int = 6,
) -> dict[str, Any]:
    if not context:
        return {}
    compacted = {
        key: _compact_value(value, text_limit=500, list_limit=8, depth=0)
        for key, value in context.items()
        if key != "events"
    }
    events = context.get("events")
    if not isinstance(events, list):
        return compacted

    selected = events[-max_events:]
    compacted_events: list[dict[str, Any]] = []
    for event in selected:
        if not isinstance(event, dict):
            continue
        output = event.get("output")
        if isinstance(output, dict):
            # The current concept is already a first-class input. Repeating every full
            # Builder concept caused contexts to grow past 60k tokens in real projects.
            output = {
                key: value
                for key, value in output.items()
                if key not in {"new_concept", "current_concept"}
            }
        compacted_events.append(
            {
                "agent": event.get("agent"),
                "stage": event.get("stage"),
                "output": _compact_value(
                    output,
                    text_limit=500,
                    list_limit=8,
                    depth=0,
                ),
            }
        )
    compacted["summary_format"] = "bounded_structured_history_v1"
    compacted["events"] = compacted_events
    if len(events) > len(selected):
        compacted["events_omitted"] = len(events) - len(selected)
    return compacted


def _compact_value(
    value: Any,
    *,
    text_limit: int,
    list_limit: int,
    depth: int,
) -> Any:
    if depth >= 4:
        return "[nested content omitted]"
    if isinstance(value, str):
        return compact_text(value, limit=text_limit)
    if isinstance(value, dict):
        return {
            str(key): _compact_value(
                item,
                text_limit=text_limit,
                list_limit=list_limit,
                depth=depth + 1,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        compacted = [
            _compact_value(
                item,
                text_limit=text_limit,
                list_limit=list_limit,
                depth=depth + 1,
            )
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            compacted.append(f"[{len(value) - list_limit} items omitted]")
        return compacted
    return value
