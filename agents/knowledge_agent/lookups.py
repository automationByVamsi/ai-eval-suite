"""
Knowledge Agent lookups for fields.yaml: fetch values the trace names only by id (see src/fields/lookup.py).
Needs HIVE_ATHENA_BASE_URL, HIVE_ATHENA_CLIENT_ID and HIVE_ATHENA_CLIENT_SECRET (env or .env).
"""

from __future__ import annotations

from typing import Any

from src.clients.athena_client import athena_http, get_page_content, page_html
from src.utils.html_text import html_to_text


def get_page_content_from_athena(page_id: str) -> dict[str, Any]:
    """Fetch one knowledge-base page from Athena as {"title", "text", "revision"}, HTML converted to text."""
    with athena_http(60) as http:
        page = get_page_content(http, page_id)
    text = html_to_text(page_html(page))
    if not text:
        raise ValueError(f"Athena returned page {page_id} without any text")
    return {"title": str(page.get("@title") or "").strip(), "text": text,
            "revision": str(page.get("@revision") or "")}
