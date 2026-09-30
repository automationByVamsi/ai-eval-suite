"""
Read fields out of a Google ADK trace, so parsers never have to learn the raw event format.

A trace is the dict saved to outputs/traces/ after every live call:

    {"agentOutput": "<final answer>", "sessionId": "...", "latency_ms": 1234.5,
     "raw_events": [ ...ADK events exactly as the agent returned them... ]}

Typical use in agents/<agent>/parser.py:

    from src.utils.adk_trace import find_event, state, tool_calls

    rewritten = state(trace, "rewritten_query", "")
    tools = [c["name"] for c in tool_calls(trace)]
"""

from __future__ import annotations

import json
from typing import Any


def final_text(events: list[dict[str, Any]]) -> str:
    """
    The agent's final answer: the last non-empty text part written by the model.

    "Thought" parts are ignored, and a leading "Answer:" line (some agents add one) is dropped.
    """
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
    """The raw ADK events of a trace ([] for traces from non-ADK agents)."""
    return trace.get("raw_events") or []


def state(trace: dict[str, Any], key: str, default: Any = None) -> Any:
    """Final value of a session-state key: the last `stateDelta` that wrote it, else `default`."""
    value = default
    for event in events(trace):
        delta = (event.get("actions") or {}).get("stateDelta") or {}
        if key in delta:
            value = delta[key]
    return value


def find_event(trace: dict[str, Any], author: str) -> dict[str, Any] | None:
    """First event written by one ADK node, e.g. find_event(trace, "query_rewrite_agent")."""
    return next((e for e in events(trace) if e.get("author") == author), None)


def event_json(event: dict[str, Any] | None) -> dict[str, Any]:
    """An event's text parsed as a JSON object; {} when it is missing or not a JSON object."""
    parts = ((event or {}).get("content") or {}).get("parts") or []
    try:
        data = json.loads(parts[0].get("text", "")) if parts else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tool the agent called, in order: [{"name": ..., "args": {...}}]."""
    calls = []
    for event in events(trace):
        for part in (event.get("content") or {}).get("parts") or []:
            # ADK has used both spellings across versions.
            call = part.get("functionCall") or part.get("function_call")
            if call and call.get("name"):
                calls.append({"name": call["name"], "args": call.get("args") or {}})
    return calls
