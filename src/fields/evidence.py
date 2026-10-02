"""
Evidence page text from Athena, for fields like (fields.yaml):

    contexts: {from: athena, ids: evidence_page_ids}

The trace says WHICH pages the agent used (ids) but not their text; Faithfulness needs the text.
So, for every id in the field named by `ids:`:

  1. already fetched in this run?          reuse it (each page is fetched once per run)
  2. OFFLINE=1 (or make fields)?           read the saved copy, never call Athena
  3. otherwise                             fetch it from Athena (clients/athena_client.py), turn the
                                           HTML into text (the synthesizer's cleaner), save a copy
Saved copies: outputs/evidence/athena/<page_id>.json  ({id, title, text, revision, fetched_at}).

The field's value is one text per page: "<title>\\n\\n<text>". If any page can't be had, the
field is left empty and the reason is reported, so the case shows an ERROR (never a low score).

Settings (env/.env): HIVE_ATHENA_BASE_URL, HIVE_ATHENA_CLIENT_ID, HIVE_ATHENA_CLIENT_SECRET —
the same ones the synthesizer uses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.core import paths

_pages: dict[str, dict[str, Any]] = {}       # page id -> saved copy, for the rest of this run


def page_texts(ids: list[Any], offline: bool) -> tuple[list[str], list[str]]:
    """([one text per page], [problems]). With any problem the texts are [] (no partial evidence)."""
    texts, problems = [], []
    for page_id in [str(i) for i in ids if str(i).strip()]:
        try:
            page = _page(page_id, offline)
            texts.append(f"{page['title']}\n\n{page['text']}".strip())
        except Exception as exc:  # noqa: BLE001 — reported as the case's error, the run carries on
            problems.append(f"page {page_id}: {type(exc).__name__}: {str(exc)[:200]}")
    return ([] if problems else texts), problems


def _page(page_id: str, offline: bool) -> dict[str, Any]:
    if page_id in _pages:
        return _pages[page_id]
    saved = _folder() / f"{page_id}.json"
    if offline:
        if not saved.is_file():
            raise FileNotFoundError("no saved copy — run once without OFFLINE=1 to fetch it from Athena")
        page = json.loads(saved.read_text())
    else:
        page = fetch_page(page_id)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(page, indent=2, ensure_ascii=False) + "\n")
    _pages[page_id] = page
    return page


def fetch_page(page_id: str) -> dict[str, Any]:
    """One page from Athena as {id, title, text, revision, fetched_at}."""
    from src.clients.athena_client import athena_http, get_page_content
    from src.synthesizer.sources.athena_mcp import page_to_text

    with athena_http(60) as http:
        raw = get_page_content(http, page_id)
    title, text = page_to_text(raw)
    if not text:
        raise ValueError("Athena returned the page without any text")
    return {"id": page_id, "title": title, "text": text, "revision": str(raw.get("@revision") or ""),
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}


def _folder():
    return paths.OUTPUTS_DIR / "evidence" / "athena"


def clear_cache() -> None:
    """Forget pages fetched earlier in this process (tests use it)."""
    _pages.clear()
