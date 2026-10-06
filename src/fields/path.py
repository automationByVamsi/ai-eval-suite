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
    first, *after_flatten = parse(path)
    value = _evaluate(first, data)
    for segment in after_flatten:              # each later segment starts after a `[]` (flatten)
        if not isinstance(value, list):
            return None
        value = [r for r in (_evaluate(segment, item) for item in _flatten(value)) if r is not None]
    return value


def parse(path: str) -> list[list[tuple[str, Any]]]:
    """
    'a.*.b[].c' -> [[('key','a'), ('all',None), ('key','b')], [('key','c')]]
    Split into segments at every `[]`; ConfigError for anything that isn't a valid path.
    """
    segments: list[list[tuple[str, Any]]] = [[]]
    text = (path or "").strip()
    position = 0
    while position < len(text):
        found = _TOKEN.match(text, position)
        if not found:
            raise ConfigError(f"Invalid path {path!r} at position {position}")
        position = found.end()
        token, index = found.group(0), found.group(1)
        match token:
            case ".":
                pass                                          # separator only
            case "[]":
                segments.append([])                           # flatten: a new segment starts
            case "*" | "[*]":
                segments[-1].append(("all", None))
            case _ if index is not None:
                segments[-1].append(("index", int(index)))    # [0], [-1]
            case _:
                segments[-1].append(("key", token.strip()))
    return segments


def _evaluate(ops: list[tuple[str, Any]], value: Any) -> Any:
    """Apply one segment's operations; `all` projects the remaining operations over the items."""
    for i, (op, arg) in enumerate(ops):
        if value is None:
            return None
        match op:
            case "key":
                value = value.get(arg) if isinstance(value, dict) else None
            case "index":
                value = value[arg] if isinstance(value, list) and -len(value) <= arg < len(value) else None
            case "all":
                items = _all_items(value)
                if items is None:
                    return None
                rest = ops[i + 1:]
                return [r for r in (_evaluate(rest, item) for item in items) if r is not None]
    return value


def _all_items(value: Any) -> list[Any] | None:
    """`*`: the values of a dict, or the items of a list (None for anything else)."""
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else None


def _flatten(items: list[Any]) -> list[Any]:
    """One level: [[a, b], c] -> [a, b, c]."""
    return [x for item in items for x in (item if isinstance(item, list) else [item])]
