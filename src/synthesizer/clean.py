"""
Turn Athena page HTML into plain, human-readable text for DeepEval synthesizer.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any


class _HTMLToText(HTMLParser):
    """Minimal HTML → text. Keeps headings / lists readable; drops scripts."""

    _BLOCK = {
        "p",
        "div",
        "section",
        "article",
        "tr",
        "table",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "br",
        "hr",
    }
    _SKIP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK:
            self._chunks.append("\n")
        if tag == "li":
            self._chunks.append("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text + " ")


def html_to_text(raw_html: str) -> str:
    """Convert an HTML fragment to clean readable text."""
    parser = _HTMLToText()
    parser.feed(raw_html or "")
    parser.close()
    text = "".join(parser._chunks)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def athena_payload_to_text(payload: dict[str, Any]) -> tuple[str, str]:
    """
    Extract (title, readable_body) from an Athena page-contents JSON.

    `body` is a list: HTML strings + optional TOC objects (`@target: toc`) which we skip.
    """
    title = str(payload.get("@title") or "").strip()
    body = payload.get("body") or []
    html_parts: list[str] = []
    if isinstance(body, list):
        for item in body:
            if isinstance(item, str):
                html_parts.append(item)
            # skip TOC / metadata dicts
    elif isinstance(body, str):
        html_parts.append(body)

    readable = html_to_text("\n".join(html_parts))
    if title:
        readable = f"{title}\n\n{readable}".strip()
    return title, readable
