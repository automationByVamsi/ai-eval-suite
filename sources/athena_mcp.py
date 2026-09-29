"""
Source `athena_mcp`: knowledge-base pages from the Hive Athena MCP server.

    source:
      type: athena_mcp
      ids_file: page_ids.json     # [{"domain": "Recoveries Commercial Bank", "page_ids": ["36626", "39696"]}]

For every page id: JSON-RPC `tools/call` -> athena_get_page_content -> page HTML -> readable text.

env/.env:
  HIVE_ATHENA_BASE_URL        e.g. https://web203-int-ew2.c2.test.lbgcp.cloud/cct1/hive1/athena-mcp-server
  HIVE_ATHENA_CLIENT_ID       sent as x-lbg-client-id
  HIVE_ATHENA_CLIENT_SECRET   sent as x-lbg-client-secret
  HIVE_ATHENA_VERIFY_TLS      true (default) | false | /path/to/ca-bundle.pem
"""

import html
import json
import os
import re
from html.parser import HTMLParser

import httpx


def fetch(settings, ids, folder):
    if not ids:
        raise ValueError("athena_mcp needs page ids — list them in ids_file or pass IDS=...")
    with httpx.Client(timeout=float(settings.get("timeout_s", 60)), verify=_verify(),
                      headers=_headers()) as http:
        documents = []
        for page_id in ids:
            page = get_page_content(http, page_id)
            title, text = page_to_text(page)
            documents.append({"id": page_id, "title": title, "text": f"{title}\n\n{text}".strip(),
                              "metadata": {"revision": str(page.get("@revision") or "")}})
        return documents


def get_page_content(http, page_id):
    """One athena_get_page_content call; returns the page JSON (@title, body, @revision)."""
    base_url = os.environ.get("HIVE_ATHENA_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ValueError("HIVE_ATHENA_BASE_URL is not set in env/.env")
    response = http.post(f"{base_url}/v1/mcp", json={
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


def page_to_text(page):
    """Athena page JSON -> (title, readable text). body = HTML strings (+ TOC objects, skipped)."""
    title = str(page.get("@title") or "").strip()
    body = page.get("body") or []
    parts = [body] if isinstance(body, str) else [item for item in body if isinstance(item, str)]
    return title, html_to_text("\n".join(parts))


def html_to_text(raw_html):
    parser = _TextOnly()
    parser.feed(raw_html or "")
    text = html.unescape("".join(parser.chunks)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _TextOnly(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "tr", "table", "ul", "ol", "li", "br", "hr",
              "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks, self.skipping = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.skipping and data.strip():
            self.chunks.append(data.strip() + " ")


def _headers():
    client_id = os.environ.get("HIVE_ATHENA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("HIVE_ATHENA_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("Set HIVE_ATHENA_CLIENT_ID and HIVE_ATHENA_CLIENT_SECRET in env/.env")
    return {"accept": "application/json, text/event-stream",
            "x-lbg-client-id": client_id, "x-lbg-client-secret": client_secret}


def _verify():
    value = os.environ.get("HIVE_ATHENA_VERIFY_TLS", "true").strip()
    return value.lower() != "false" if value.lower() in ("true", "false") else value


def _json_body(text):
    """Plain JSON, or a server-sent-events body ('data: {...}') — MCP servers can answer either way."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise RuntimeError(f"Athena MCP returned neither JSON nor event-stream data: {text[:200]}")
    return json.loads(data_lines[-1])
