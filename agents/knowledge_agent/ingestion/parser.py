"""
Measures the Markdown against the Athena page it was made from (checks.yaml compares the numbers):

    source_headings / md_headings          <h1>-<h6>          vs  lines starting with #
    source_list_items / md_list_items      <li>               vs  "- item", "* item", "1. item"
    source_table_rows / md_table_rows      <tr>               vs  "| a | b |" rows (not the |---| line)
    source_links / md_links                <a href=...>       vs  [text](url)
    text_coverage                          share of the page's lines of text found in the Markdown
    missing_lines                          the first 10 lines that weren't found (to see what was lost)

Text is compared ignoring case, spacing and Markdown symbols, so "**Step 1:** Open" matches "Step 1: Open".
"""

import re
from html.parser import HTMLParser

from src.utils.html_text import html_to_text


def parse(trace, case):
    html, markdown = trace["athena"]["html"], trace["agentOutput"]
    source = _html_counts(html)
    lines = markdown.splitlines()
    found, missing = _coverage(html_to_text(html), markdown)
    return {
        "source_headings": source["h"], "md_headings": _count(lines, r"^\s{0,3}#{1,6}\s"),
        "source_list_items": source["li"], "md_list_items": _count(lines, r"^\s*(?:[-*+]|\d+[.)])\s+"),
        "source_table_rows": source["tr"], "md_table_rows": _count(lines, r"^\s*\|(?!\s*:?-{3,})"),
        "source_links": source["a"], "md_links": len(re.findall(r"\[[^\]]*\]\([^)]+\)", markdown)),
        "text_coverage": found,
        "missing_lines": missing[:10],
    }


def _count(lines, pattern):
    return sum(1 for line in lines if re.match(pattern, line))


def _html_counts(html):
    """How many headings, list items, table rows and links the page's HTML has."""
    counts = {"h": 0, "li": 0, "tr": 0, "a": 0}

    class Counter(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if re.fullmatch(r"h[1-6]", tag):
                counts["h"] += 1
            elif tag in ("li", "tr") or (tag == "a" and dict(attrs).get("href")):
                counts[tag] += 1

    Counter().feed(html or "")
    return counts


def _coverage(source_text, markdown):
    """(share of the source's lines of text found in the Markdown, the lines that weren't)."""
    lines = [_plain(line.removeprefix("- ")) for line in source_text.splitlines()]
    lines = [line for line in lines if len(line) > 2]
    markdown = _plain(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown))       # [text](url) -> text
    missing = [line for line in lines if line not in markdown]
    return (round(1 - len(missing) / len(lines), 4) if lines else 1.0), missing


def _plain(text):
    """Lower case, no Markdown symbols, single spaces, no space before punctuation ("Needs ." = "Needs.")."""
    text = " ".join(re.sub(r"[#*_`|>]", " ", text).casefold().split())
    return re.sub(r" ([.,;:!?)])", r"\1", text)
