"""
Everything about Google ADK agents: call one, and read fields out of its trace.

A trace is the dict we save to disk after every live call:

    {"agentOutput": "<final answer>", "sessionId": "...", "latency_ms": 1234.5,
     "raw_events": [ ...ADK events exactly as the agent returned them... ]}

Parsers use the helpers at the bottom (state, find_event, event_json, tool_calls)
so nobody has to learn the raw ADK event format.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


class AgentCallError(Exception):
    """The agent could not be reached or returned something unusable."""


def call_agent(adk: dict[str, Any], message: str) -> dict[str, Any]:
    """Create an ADK session, send one message to /run, return the trace."""
    base = str(adk["base_url"]).rstrip("/") + str(adk.get("base_path") or "")
    app = adk["app_name"]
    user = adk.get("user_id") or "eval_user"
    retries = int(adk.get("retries", 1))
    client_args = {
        "timeout": float(adk.get("timeout_s", 120)),
        "verify": _verify(adk.get("verify_tls", True)),
        "headers": _headers(adk.get("headers") or {}),
    }

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            with httpx.Client(**client_args) as http:
                session = http.post(f"{base}/apps/{app}/users/{user}/sessions", json={})
                session.raise_for_status()
                session_id = session.json()["id"]
                run = http.post(f"{base}/run", json={
                    "app_name": app,
                    "user_id": user,
                    "session_id": session_id,
                    "new_message": {"role": "user", "parts": [{"text": message}]},
                })
                run.raise_for_status()
                events = run.json()
            return {
                "agentOutput": final_text(events),
                "sessionId": session_id,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "raw_events": events,
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:  # 4xx: wrong URL/auth — retrying won't help
                raise AgentCallError(f"{app}: HTTP {exc.response.status_code} {exc.response.text[:300]}") from exc
            last_error = exc
        except (httpx.TransportError, KeyError, ValueError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(2)
    raise AgentCallError(f"{app}: failed after {retries + 1} attempt(s): {last_error}")


def final_text(events: list[dict[str, Any]]) -> str:
    """Last non-thought text the model produced (drops a leading 'Answer:' wrapper)."""
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


# --- Reading a trace -------------------------------------------------------------------------

def events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return trace.get("raw_events") or []


def state(trace: dict[str, Any], key: str, default: Any = None) -> Any:
    """Final value of a session-state key (last stateDelta that wrote it)."""
    value = default
    for event in events(trace):
        delta = (event.get("actions") or {}).get("stateDelta") or {}
        if key in delta:
            value = delta[key]
    return value


def find_event(trace: dict[str, Any], author: str) -> dict[str, Any] | None:
    """First event written by a given ADK node, e.g. find_event(trace, "query_rewrite_agent")."""
    return next((e for e in events(trace) if e.get("author") == author), None)


def event_json(event: dict[str, Any] | None) -> dict[str, Any]:
    """An event's text parsed as JSON ({} if it isn't JSON)."""
    parts = ((event or {}).get("content") or {}).get("parts") or []
    try:
        data = json.loads(parts[0].get("text", "")) if parts else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tool the agent called: [{"name": ..., "args": {...}}] in call order."""
    calls = []
    for event in events(trace):
        for part in (event.get("content") or {}).get("parts") or []:
            call = part.get("functionCall") or part.get("function_call")
            if call and call.get("name"):
                calls.append({"name": call["name"], "args": call.get("args") or {}})
    return calls


def _verify(value: Any) -> bool | str:
    """verify_tls: true | false | /path/to/ca-bundle.pem"""
    if isinstance(value, str) and value.strip().lower() in ("true", "false", ""):
        return value.strip().lower() != "false"
    return value


def _headers(headers: dict[str, Any]) -> dict[str, str]:
    empty = [k for k, v in headers.items() if not str(v or "").strip()]
    if empty:
        raise AgentCallError(f"Header(s) {empty} are empty — set the matching variable in .env")
    return {str(k): str(v) for k, v in headers.items()}
