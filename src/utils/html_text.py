"""
HTML -> readable plain text, for sources that return HTML (e.g. Athena knowledge-base pages).

Block elements (paragraphs, table rows, headings...) become line breaks, list items become
"- " bullets, and <script>/<style> content is dropped.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def html_to_text(raw_html: str) -> str:
    """Readable text from an HTML string, with at most one blank line between blocks."""
    parser = _TextOnly()
    parser.feed(raw_html or "")
    text = html.unescape("".join(parser.chunks)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _TextOnly(HTMLParser):
    """Collects text chunks; adds a newline at block boundaries."""

    BLOCKS = {"p", "div", "section", "article", "tr", "table", "ul", "ol", "li", "br", "hr",
              "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.skipping = 0            # > 0 while inside <script>/<style>/<noscript>

    def handle_starttag(self, tag, attrs):  # noqa: ANN001 — HTMLParser's signature
        if tag in self.SKIP:
            self.skipping += 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        if not self.skipping and data.strip():
            self.chunks.append(data.strip() + " ")
