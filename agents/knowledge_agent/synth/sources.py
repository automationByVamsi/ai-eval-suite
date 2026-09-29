"""
Fetch knowledge-base pages from Athena for the synthesizer.

    make sources AGENT=knowledge_agent IDS="8708 9001"

The framework calls fetch(page_id) for every id and saves the result as sources/<id>.txt.
Settings in .env: ATHENA_BASE_URL, ATHENA_ID (sent as x-lbg-origin-client-id), ATHENA_VERIFY_TLS.
"""

import html
import os
import re
from html.parser import HTMLParser

import httpx


def fetch(page_id):
    """Return (title, readable text) for one Athena page."""
    base_url = os.environ.get("ATHENA_BASE_URL", "").rstrip("/")
    client_id = os.environ.get("ATHENA_ID", "")
    if not base_url or not client_id:
        raise ValueError("Set ATHENA_BASE_URL and ATHENA_ID in .env")
    response = httpx.get(
        f"{base_url}/control-plane/v1/pages/{page_id}/contents",
        params={"format": "json"},
        headers={"x-lbg-origin-client-id": client_id},
        verify=os.environ.get("ATHENA_VERIFY_TLS", "true").lower() != "false",
        timeout=60,
    )
    response.raise_for_status()
    return page_to_text(response.json())


def page_to_text(page):
    """Athena page JSON -> (title, text). The body is a list of HTML strings (plus TOC objects we skip)."""
    title = str(page.get("@title") or "").strip()
    body = page.get("body") or []
    parts = [body] if isinstance(body, str) else [item for item in body if isinstance(item, str)]
    return title, html_to_text("\n".join(parts))


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


def html_to_text(raw_html):
    parser = _TextOnly()
    parser.feed(raw_html or "")
    text = html.unescape("".join(parser.chunks)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
