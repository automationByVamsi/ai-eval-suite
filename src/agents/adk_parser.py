"""
Best-effort field extraction from a raw captured ADK agent trace: a dict with
a top-level "agentOutput" string and a "raw_events" list of native ADK event
objects (author, content.parts[].text, actions.stateDelta, nodeInfo.path).
Both the live ADK adapter and offline stage parsers reuse this so the "what
does a raw ADK trace look like" knowledge lives in exactly one place.
"""

import json
from typing import Any


def extract_answer(raw: dict[str, Any]) -> str:
    return raw.get("agentOutput") or ""


def extract_context(raw: dict[str, Any]) -> list[str]:
    return raw.get("context") or []


def extract_events(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return raw.get("raw_events") or []


def extract_session_id(raw: dict[str, Any]) -> str | None:
    return raw.get("sessionId")


def extract_latency_ms(raw: dict[str, Any]) -> float | None:
    return raw.get("latency_ms")


def find_event_by_author(raw: dict[str, Any], author: str) -> dict[str, Any] | None:
    """Returns the first event produced by a given ADK node, e.g. find_event_by_author(raw, 'query_rewrite_agent')."""
    for event in extract_events(raw):
        if event.get("author") == author:
            return event
    return None


def event_json(event: dict[str, Any]) -> dict[str, Any]:
    """Parses an event's model text output as JSON (ADK agent turns are JSON-only by convention)."""
    parts = event.get("content", {}).get("parts", [])
    text = parts[0].get("text", "") if parts else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def state_after(raw: dict[str, Any], key: str) -> Any:
    """The last non-empty value written to `key` across every event's stateDelta - i.e. its final session-state value."""
    value = None
    for event in extract_events(raw):
        delta = event.get("actions", {}).get("stateDelta", {})
        if delta.get(key):
            value = delta[key]
    return value
