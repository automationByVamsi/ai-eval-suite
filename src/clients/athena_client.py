"""Read knowledge-base pages from the Hive Athena MCP server (one JSON-RPC call per page).

Settings: HIVE_ATHENA_BASE_URL, HIVE_ATHENA_CLIENT_ID, HIVE_ATHENA_CLIENT_SECRET in env/.env.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.core import tls
from src.core.env import require


def athena_http(timeout_s: float = 60) -> httpx.Client:
    """Return an httpx client with the Athena auth headers; use it in a `with` block."""
    return httpx.Client(
        timeout=timeout_s,
        verify=tls.httpx_verify(),
        headers={
            # MCP servers may answer as plain JSON or as a server-sent event; accept both.
            "accept": "application/json, text/event-stream",
            "x-lbg-client-id": require("HIVE_ATHENA_CLIENT_ID"),
            "x-lbg-client-secret": require("HIVE_ATHENA_CLIENT_SECRET"),
        },
    )


def mcp_url() -> str:
    """Return the MCP endpoint URL, adding /v1/mcp to HIVE_ATHENA_BASE_URL if it is missing."""
    base_url = require("HIVE_ATHENA_BASE_URL").rstrip("/")
    return base_url if base_url.endswith("/v1/mcp") else f"{base_url}/v1/mcp"


def get_page_content(http: httpx.Client, page_id: str) -> dict[str, Any]:
    """Fetch one page as {"@title", "@revision", "body"}; raises RuntimeError on an error or unexpected shape."""
    response = http.post(mcp_url(), json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "athena_get_page_content", "arguments": {"pageId": str(page_id), "format": "json"}},
    })
    response.raise_for_status()
    data = _json_body(response.text)
    if "error" in data:
        raise RuntimeError(f"Athena page {page_id}: {data['error']}")
    try:
        value = data["result"]["structuredContent"]["result"]["value"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Athena page {page_id}: unexpected response shape ({exc}): {str(data)[:300]}") from exc
    if not isinstance(value, dict) or "errors" in value:
        raise RuntimeError(f"Athena page {page_id}: {value.get('errors') if isinstance(value, dict) else value}")
    return value


def page_html(page: dict[str, Any]) -> str:
    """Return the HTML parts of a page's body as one string, skipping table-of-contents objects."""
    body = page.get("body") or []
    return "\n".join([body] if isinstance(body, str) else [part for part in body if isinstance(part, str)])


def _json_body(text: str) -> dict[str, Any]:
    """Parse a plain JSON or server-sent-events body; for SSE the last 'data:' line is the answer."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise RuntimeError(f"Athena MCP returned neither JSON nor event-stream data: {text[:200]}")
    return json.loads(data_lines[-1])
