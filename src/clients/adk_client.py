"""
Call a Google ADK agent over HTTP and return its trace.

Two requests per test case:
  1. POST {base_url}{base_path}/apps/{app_name}/users/{user_id}/sessions   -> {"id": session_id}
  2. POST {base_url}{base_path}/run   with the message                      -> list of ADK events

Settings come from `connection:` in agents/<agent>/agent.yaml (values from env/.env):
  base_url, base_path, app_name, user_id, timeout_s, retries, verify_tls, headers

Used by: runners/suite_runner.py, for every agent that has no client.py of its own.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.core.env import tls_setting
from src.core.exceptions import AgentCallError
from src.utils.adk_trace import final_text


def call_agent(connection: dict[str, Any], message: str) -> dict[str, Any]:
    """
    Create a session, send one message, and return the trace:
        {"agentOutput", "sessionId", "latency_ms", "raw_events"}

    Retries only when a retry can help (5xx, timeouts, dropped connections). A 4xx means the
    URL, app name or auth is wrong, so it fails at once with the server's message.
    """
    base = str(connection["base_url"]).rstrip("/") + str(connection.get("base_path") or "")
    app = connection["app_name"]
    user = connection.get("user_id") or "eval_user"
    retries = int(connection.get("retries", 1))
    client_args = {
        "timeout": float(connection.get("timeout_s", 120)),
        "verify": tls_setting(connection.get("verify_tls", True)),
        "headers": _headers(connection.get("headers") or {}),
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
            if exc.response.status_code < 500:
                raise AgentCallError(f"{app}: HTTP {exc.response.status_code} {exc.response.text[:300]}") from exc
            last_error = exc
        except (httpx.TransportError, KeyError, ValueError) as exc:
            # Network trouble, or a reply without a session id / not JSON: worth another try.
            last_error = exc
        if attempt < retries:
            time.sleep(2)
    raise AgentCallError(f"{app}: failed after {retries + 1} attempt(s): {last_error}")


def _headers(headers: dict[str, Any]) -> dict[str, str]:
    """Extra request headers from agent.yaml. An empty value means an env variable is missing."""
    empty = [k for k, v in headers.items() if not str(v or "").strip()]
    if empty:
        raise AgentCallError(f"Header(s) {empty} are empty — set the matching variable in env/.env")
    return {str(k): str(v) for k, v in headers.items()}
