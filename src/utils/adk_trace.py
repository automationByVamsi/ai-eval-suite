"""Read values out of a Google ADK trace (final answer, state, events, tool calls) without touching raw events."""

from __future__ import annotations

import json
from typing import Any


def final_text(events: list[dict[str, Any]]) -> str:
    """Return the last non-empty, non-thought model text, minus any leading "Answer:" line."""
    text = ""
    for event in events:
        content = event.get("content") or {}
        if content.get("role") not in (None, "model"):
            continue
        for part in content.get("parts") or []:
            if isinstance(part, dict) and "thought" not in part and str(part.get("text") or "").strip():
                text = part["text"].strip()
    if "Answer:\n" in text:
        text = text.split("Answer:\n", 1)[1].strip()
    return text


def events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the trace's raw ADK events ([] for non-ADK agents)."""
    return trace.get("raw_events") or []


def state(trace: dict[str, Any], key: str, default: Any = None) -> Any:
    """Return a session-state key's value from the last `stateDelta` that wrote it, else `default`."""
    value = default
    for event in events(trace):
        delta = (event.get("actions") or {}).get("stateDelta") or {}
        if key in delta:
            value = delta[key]
    return value


def find_event(trace: dict[str, Any], author: str) -> dict[str, Any] | None:
    """Return the first event written by `author`, or None."""
    return next((e for e in events(trace) if e.get("author") == author), None)


def event_json(event: dict[str, Any] | None) -> dict[str, Any]:
    """Return an event's text parsed as a JSON object; {} when missing or not a JSON object."""
    parts = ((event or {}).get("content") or {}).get("parts") or []
    try:
        data = json.loads(parts[0].get("text", "")) if parts else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every tool call in order as [{"name": ..., "args": {...}}]."""
    calls = []
    for event in events(trace):
        for part in (event.get("content") or {}).get("parts") or []:
            # ADK has used both spellings across versions.
            call = part.get("functionCall") or part.get("function_call")
            if call and call.get("name"):
                calls.append({"name": call["name"], "args": call.get("args") or {}})
    return calls
