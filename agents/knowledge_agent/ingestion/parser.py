"""
Measures the pipeline's Markdown against the HTML it was made from (checks.yaml compares the numbers).

The source HTML is first cleaned the way the pipeline cleans it (html_to_markdown.py), so the
pipeline's own deliberate rules are not counted as losses:
    - HTML escaped several times is unescaped until it stops changing
    - hidden blocks are dropped: data-llm-no-index="true", #recent-changes, <script>, <style>,
      the table of contents (body target="toc"), and images

Then, source (cleaned HTML) vs Markdown:
    headings     <h1>-<h6>                                vs  lines starting with #
    list_items   <li> (not inside a table: the pipeline   vs  "- item", "* item", "1. item"
                 flattens lists in table cells to text)
    table_rows   <tr>                                     vs  "| a | b |" rows (not the |---| line)
    links        <a> with text (the pipeline keeps        vs  [text]  or  [text](url)
                 only the text: "[Customer Support]")
    callouts     warning / caution / notes / tip boxes    vs  "> **WARNING** ...", "> **INFORMATION** ..."

    text_coverage   share of the source's lines of text found in the Markdown
    differences     what is missing, what was added, and every count side by side ("16 -> 8")
    summary         one line: "no differences" or "list items 16 -> 8 · 2 lines missing"

answer / contexts are what the LLM judges get: the Markdown, and the cleaned source as plain text.
Text is compared ignoring case, spacing and Markdown symbols, so "**Step 1:** Open" matches "Step 1: Open".
"""

import html
import re
from html.parser import HTMLParser

from src.utils.html_text import html_to_text

CALLOUT_CLASSES = ("mt-warning-container", "mt-caution-container", "mt-notes-container", "mt-tip-container")
CALLOUT_LABEL = r"\*\*(?:WARNING|CAUTION|INFORMATION|TIP)\*\*"
VOID_TAGS = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
NAMES = {"headings": "headings", "list_items": "list items", "table_rows": "table rows", "links": "links",
         "callouts": "callouts"}


def parse(trace, case):
    source_html = clean_html(trace["source_html"])
    markdown = trace["markdown"]
    title = trace.get("athena", {}).get("title", "")
    source_text = html_to_text(source_html)
    source, md = html_counts(source_html), markdown_counts(markdown)
    missing, added = missing_lines(source_text, markdown), added_lines(source_text, markdown)
    lines = [line for line in source_text.splitlines() if len(_plain(line)) > 2]
    counts = {NAMES[k]: f"{source[k]} → {md[k]}" for k in NAMES}

    fields = {f"source_{k}": v for k, v in source.items()} | {f"md_{k}": v for k, v in md.items()}
    return fields | {
        "answer": markdown,
        "contexts": [f"{title}\n\n{source_text}".strip()],
        "text_coverage": round(1 - len(missing) / len(lines), 4) if lines else 1.0,
        "differences": {"counts": counts, "missing_lines": missing[:10], "added_lines": added[:10]},
        "summary": summary(source, md, missing, added),
    }


def summary(source, md, missing, added):
    """'no differences', or e.g. 'list items 16 → 8 · 2 lines missing · 1 line added'."""
    bits = [f"{NAMES[k]} {source[k]} → {md[k]}" for k in NAMES if source[k] != md[k]]
    if missing:
        bits.append(f"{len(missing)} line{'s' * (len(missing) > 1)} missing")
    if added:
        bits.append(f"{len(added)} line{'s' * (len(added) > 1)} added")
    return " · ".join(bits) or "no differences"


# --- the source HTML ------------------------------------------------------------------------------

def clean_html(raw):
    """The HTML the pipeline converts: unescaped until stable, hidden blocks and images removed."""
    for _ in range(5):
        unescaped = html.unescape(raw or "")
        if unescaped == raw:
            break
        raw = unescaped
    cleaner = _Cleaner()
    cleaner.feed(raw or "")
    cleaner.close()
    return "".join(cleaner.out)


def _hidden(tag, attrs):
    """True for the blocks the pipeline drops before converting (NON_CONTENT_SELECTORS)."""
    return (tag in ("script", "style") or attrs.get("data-llm-no-index") == "true"
            or attrs.get("id") == "recent-changes" or (tag == "body" and attrs.get("target") == "toc"))


class _Cleaner(HTMLParser):
    """Writes the HTML back out without the hidden blocks and images."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.hiding, self.depth = [], None, 0      # hiding: the tag of the hidden block we are in

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.hiding:
            self.depth += tag == self.hiding
        elif tag == "img":
            pass
        elif _hidden(tag, attrs) and tag not in VOID_TAGS:
            self.hiding, self.depth = tag, 1
        else:
            text = "".join(f' {k}="{html.escape(v or "")}"' for k, v in attrs.items())
            self.out.append(f"<{tag}{text}>")

    def handle_endtag(self, tag):
        if self.hiding:
            self.depth -= tag == self.hiding
            if not self.depth:
                self.hiding = None
        elif tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.hiding:
            self.out.append(html.escape(data, quote=False))


def html_counts(cleaned):
    """How many headings, list items (outside tables), table rows, links with text and callouts."""
    counts = dict.fromkeys(NAMES, 0)

    class Counter(HTMLParser):
        tables, link_text = 0, None

        def handle_starttag(self, tag, attrs):
            classes = (dict(attrs).get("class") or "").split()
            if re.fullmatch(r"h[1-6]", tag):
                counts["headings"] += 1
            elif tag == "table":
                self.tables += 1
            elif tag == "tr":
                counts["table_rows"] += 1
            elif tag == "li" and not self.tables:
                counts["list_items"] += 1
            elif tag == "a":
                self.link_text = ""
            elif tag == "div" and any(c in classes for c in CALLOUT_CLASSES):
                counts["callouts"] += 1

        def handle_endtag(self, tag):
            if tag == "table" and self.tables:
                self.tables -= 1
            elif tag == "a" and self.link_text is not None:
                counts["links"] += bool(self.link_text.strip())
                self.link_text = None

        def handle_data(self, data):
            if self.link_text is not None:
                self.link_text += data

    Counter().feed(cleaned)
    return counts


# --- the Markdown ---------------------------------------------------------------------------------

def markdown_counts(markdown):
    """The same counts in the Markdown (a callout's lines start with "> ", so that is ignored first)."""
    lines = markdown.splitlines()
    inner = [re.sub(r"^(\s*>\s?)+", "", line) for line in lines]
    return {
        "headings": _count(inner, r"^\s{0,3}#{1,6}\s"),
        "list_items": _count(inner, r"^\s*(?:[-*+]|\d+[.)])\s+"),
        "table_rows": _count(inner, r"^\s*\|(?!\s*:?-{3,})"),
        "links": sum(1 for text in re.findall(r"\[([^\]\n]*)\]", markdown) if text.strip()),
        "callouts": _count(lines, rf"^\s*>\s*{CALLOUT_LABEL}"),
    }


def _count(lines, pattern):
    return sum(1 for line in lines if re.match(pattern, line))


# --- the text -------------------------------------------------------------------------------------

def missing_lines(source_text, markdown):
    """The source's lines of text that are not in the Markdown."""
    everything = _plain(_markdown_text(markdown))
    lines = [_plain(line.removeprefix("- ")) for line in source_text.splitlines()]
    return [line for line in lines if len(line) > 2 and line not in everything]


def added_lines(source_text, markdown):
    """The Markdown's lines of text that are not in the source (callout labels and |---| lines aside)."""
    everything = _plain(source_text.replace("\n- ", "\n"))
    added = []
    for line in _markdown_text(markdown).splitlines():
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", re.sub(rf"^(\s*>\s?)+|{CALLOUT_LABEL}", "", line))
        line = _plain(line)
        if len(line) > 2 and not re.fullmatch(r"[\s:|-]+", line) and line not in everything:
            added.append(line)
    return added


def _markdown_text(markdown):
    """The Markdown without link syntax and escapes: '[Card](/p/2)' -> 'Card', '\\_' -> '_'."""
    text = re.sub(r"\[([^\]\n]*)\]\([^)]*\)", r"\1", markdown)
    text = re.sub(r"\[([^\]\n]*)\]", r"\1", text)
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", text)


def _plain(text):
    """Lower case, no Markdown symbols, single spaces, no space before punctuation ("Needs ." = "Needs.")."""
    text = " ".join(re.sub(r"[#*_`|>]", " ", text).casefold().split())
    return re.sub(r" ([.,;:!?)])", r"\1", text)
