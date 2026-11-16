"""Convert HTML (e.g. Athena pages) to readable plain text: blocks become lines, list items become "- " bullets."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def html_to_text(raw_html: str) -> str:
    """Return readable text from HTML, with at most one blank line between blocks."""
    parser = _TextOnly()
    parser.feed(raw_html or "")
    text = html.unescape("".join(parser.chunks)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _TextOnly(HTMLParser):
    """HTML parser that collects text chunks, adding newlines at block boundaries and skipping scripts."""

    BLOCKS = {"p", "div", "section", "article", "tr", "table", "ul", "ol", "li", "br", "hr",
              "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        """Start with no chunks, not inside a skipped tag."""
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.skipping = 0            # > 0 while inside <script>/<style>/<noscript>

    def handle_starttag(self, tag, attrs):  # noqa: ANN001 — HTMLParser's signature
        """Enter a skipped tag, or add a line break (or bullet) for a block tag."""
        if tag in self.SKIP:
            self.skipping += 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        """Leave a skipped tag, or add a line break after a block tag."""
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif not self.skipping and tag in self.BLOCKS:
            self.chunks.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        """Keep non-blank text outside skipped tags."""
        if not self.skipping and data.strip():
            self.chunks.append(data.strip() + " ")
