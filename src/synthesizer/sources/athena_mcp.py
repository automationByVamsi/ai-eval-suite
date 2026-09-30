"""
Source `athena_mcp`: knowledge-base pages from the Hive Athena MCP server.

    source:
      type: athena_mcp
      ids_file: page_ids.json     # [{"domain": "Recoveries Commercial Bank", "page_ids": ["36626", "39696"]}]
      timeout_s: 60               # optional

For every page id: fetch the page (clients/athena_client.py), then turn its HTML into readable
text. Connection settings (HIVE_ATHENA_*) are in env/.env — see the client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.clients.athena_client import athena_http, get_page_content
from src.utils.html_text import html_to_text


def fetch(settings: dict[str, Any], ids: list[str] | None, folder: Path) -> list[dict[str, Any]]:
    """One document per page id. Athena has no "list everything", so ids are required."""
    if not ids:
        raise ValueError("athena_mcp needs page ids — list them in ids_file or pass IDS=...")
    documents = []
    with athena_http(float(settings.get("timeout_s", 60))) as http:
        for page_id in ids:
            page = get_page_content(http, page_id)
            title, text = page_to_text(page)
            documents.append({"id": page_id, "title": title, "text": f"{title}\n\n{text}".strip(),
                              "metadata": {"revision": str(page.get("@revision") or "")}})
    return documents


def page_to_text(page: dict[str, Any]) -> tuple[str, str]:
    """Athena page JSON -> (title, readable text). `body` holds HTML strings and TOC objects (skipped)."""
    title = str(page.get("@title") or "").strip()
    body = page.get("body") or []
    parts = [body] if isinstance(body, str) else [item for item in body if isinstance(item, str)]
    return title, html_to_text("\n".join(parts))
