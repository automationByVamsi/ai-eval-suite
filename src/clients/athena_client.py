"""
Hive Athena MCP server: read knowledge-base pages.

One JSON-RPC call per page:
    POST {HIVE_ATHENA_BASE_URL}/v1/mcp
    {"method": "tools/call", "params": {"name": "athena_get_page_content",
                                         "arguments": {"pageId": "<id>", "format": "json"}}}
The page JSON (@title, body, @revision) is at result.structuredContent.result.value.

Settings (env/.env):
  HIVE_ATHENA_BASE_URL        e.g. https://web203-int-ew2.c2.test.lbgcp.cloud/cct1/hive1/athena-mcp-server
  HIVE_ATHENA_CLIENT_ID       sent as x-lbg-client-id
  HIVE_ATHENA_CLIENT_SECRET   sent as x-lbg-client-secret

Certificate checks follow VERIFY_TLS / CA_BUNDLE (src/core/tls.py).

Used by: synthesizer/sources/athena_mcp.py, agents/knowledge_agent/lookups.py, agents/ka_ingestion/client.py.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.core import tls
from src.core.env import require


def athena_http(timeout_s: float = 60) -> httpx.Client:
    """An HTTP client with the Athena auth headers. Use it in a `with` block."""
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
    """HIVE_ATHENA_BASE_URL + /v1/mcp — the base URL may be given with or without the /v1/mcp."""
    base_url = require("HIVE_ATHENA_BASE_URL").rstrip("/")
    return base_url if base_url.endswith("/v1/mcp") else f"{base_url}/v1/mcp"


def get_page_content(http: httpx.Client, page_id: str) -> dict[str, Any]:
    """One page as Athena returns it: {"@title", "@revision", "body": [html strings / TOC objects]}."""
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
    """The page's content as one HTML string: the HTML parts of its body (table-of-contents objects left out)."""
    body = page.get("body") or []
    return "\n".join([body] if isinstance(body, str) else [part for part in body if isinstance(part, str)])


def _json_body(text: str) -> dict[str, Any]:
    """Plain JSON, or a server-sent-events body ('data: {...}' lines — the last one is the answer)."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise RuntimeError(f"Athena MCP returned neither JSON nor event-stream data: {text[:200]}")
    return json.loads(data_lines[-1])
