"""
Load Fact Find complaint-reference groups from
data/fact_find_workflow/complaint-references.json

Supports the same shapes as the Playwright suite:
  { "positive": [...], "negative": [...], "edge": [...] }
  { "complaintRefs": [...] }   → treated as positive only
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_REFS_PATH = Path("data/fact_find_workflow/complaint-references.json")


def load_ref_groups(path: str | Path | None = None) -> dict[str, list[str]]:
    """Load complaint refs and normalize them into named groups."""
    path = Path(path) if path else DEFAULT_REFS_PATH
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    if isinstance(data.get("complaintRefs"), list):
        return {
            "positive": _unique_strings(data["complaintRefs"]),
            "negative": [],
            "edge": [],
        }

    groups: dict[str, list[str]] = {}
    for name, refs in data.items():
        if isinstance(refs, list):
            groups[name] = _unique_strings(refs)
    return groups


def all_refs(path: str | Path | None = None, groups: list[str] | None = None) -> list[str]:
    """Return unique refs from the selected groups in file order."""
    ref_groups = load_ref_groups(path)
    selected = groups or list(ref_groups.keys())
    out: list[str] = []
    seen: set[str] = set()
    for name in selected:
        for ref in ref_groups.get(name, []):
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
    return out


def _unique_strings(items: list[Any]) -> list[str]:
    """Trim values, drop blanks, and preserve first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
