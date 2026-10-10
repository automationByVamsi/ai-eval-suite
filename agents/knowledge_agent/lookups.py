"""
Knowledge Agent lookups: values the trace only names by id, fetched from where the agent got them.
fields.yaml uses them as, e.g.

    contexts: {lookup: get_page_content_from_athena, ids: evidence_page_ids}

The framework calls each function once per id per run, saves the result under
outputs/lookups/knowledge_agent/<function>/<id>.json (OFFLINE=1 reuses it), and turns any exception
into an ERROR on the case — see src/fields/lookup.py. A function only has to return the value.

Settings (env/.env): HIVE_ATHENA_BASE_URL, HIVE_ATHENA_CLIENT_ID, HIVE_ATHENA_CLIENT_SECRET.
"""

from __future__ import annotations

from typing import Any

from src.clients.athena_client import athena_http, get_page_content, page_html
from src.utils.html_text import html_to_text


def get_page_content_from_athena(page_id: str) -> dict[str, Any]:
    """
    One knowledge-base page as {"title", "text", "revision"}: Athena's athena_get_page_content
    (the same call as the "Get Page Content" request in Bruno), with the HTML turned into text.

    Athena returns {"@title", "@revision", "body": [HTML strings, and table-of-contents objects]};
    only the HTML strings are page content.
    """
    with athena_http(60) as http:
        page = get_page_content(http, page_id)
    text = html_to_text(page_html(page))
    if not text:
        raise ValueError(f"Athena returned page {page_id} without any text")
    return {"title": str(page.get("@title") or "").strip(), "text": text,
            "revision": str(page.get("@revision") or "")}
