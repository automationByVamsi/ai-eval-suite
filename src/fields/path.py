"""
Paths into JSON — a small, dependency-free subset of JMESPath (https://jmespath.org), so you can
try an expression on jmespath.org and it means the same thing here.

    answer.summary                    a key inside a key
    evidence[0]  evidence[-1]         one item of a list (0 = first, -1 = last)
    evidence[].title                  every item's title            -> ["How To ...", "Consent ..."]
    search_branches.*.anchor_page_id  every value of a dict, then a key (for dicts keyed by random ids)
    search_branches.*.filtered_page_ids[]      ... and flatten the lists into one list
    search_branches.*.llm_selected_expansion[][1]   flatten, then item 1 of every pair

Rules (the same as JMESPath):
  - a missing key or index gives None, never an error
  - `*` and `[*]` run the rest of the path on every item and collect the results (None dropped)
  - `[]` flattens what is on its left by one level, then runs the rest on every item
"""

from __future__ import annotations

import re
from typing import Any

from src.core.exceptions import ConfigError

_TOKEN = re.compile(r"\[\]|\[\*\]|\[(-?\d+)\]|\*|[^.\[\]*]+|\.")


def get(data: Any, path: str) -> Any:
    """The value at `path` in `data` (see the top of this file). An empty path returns `data`."""
    segments = parse(path)
    value = _evaluate(segments[0], data)
    for segment in segments[1:]:               # each later segment starts after a `[]` (flatten)
        if not isinstance(value, list):
            return None
        flat: list[Any] = []
        for item in value:
            flat.extend(item) if isinstance(item, list) else flat.append(item)
        value = [r for r in (_evaluate(segment, item) for item in flat) if r is not None]
    return value


def parse(path: str) -> list[list[tuple[str, Any]]]:
    """
    'a.*.b[].c' -> [[('key','a'), ('all',None), ('key','b')], [('key','c')]]
    Split into segments at every `[]`; ConfigError for anything that isn't a valid path.
    """
    segments: list[list[tuple[str, Any]]] = [[]]
    position = 0
    text = (path or "").strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise ConfigError(f"Invalid path {path!r} at position {position}")
        token = match.group(0)
        position = match.end()
        if token == ".":
            continue
        if token == "[]":
            segments.append([])
        elif token in ("*", "[*]"):
            segments[-1].append(("all", None))
        elif match.group(1) is not None:
            segments[-1].append(("index", int(match.group(1))))
        else:
            segments[-1].append(("key", token.strip()))
    return segments


def _evaluate(ops: list[tuple[str, Any]], value: Any) -> Any:
    """Apply one segment's operations; `all` projects the remaining operations over the items."""
    for i, (op, arg) in enumerate(ops):
        if value is None:
            return None
        if op == "key":
            value = value.get(arg) if isinstance(value, dict) else None
        elif op == "index":
            value = value[arg] if isinstance(value, list) and -len(value) <= arg < len(value) else None
        else:  # "all"
            items = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else None
            if items is None:
                return None
            rest = ops[i + 1:]
            return [r for r in (_evaluate(rest, item) for item in items) if r is not None]
    return value
