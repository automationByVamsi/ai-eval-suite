"""Resolve saved ADK traces for any agent/suite."""

from __future__ import annotations

from pathlib import Path


def resolve_trace_path(
    case_id: str,
    *,
    agent: str,
    suite: str = "sanity",
    traces_root: str | Path = "outputs/traces",
) -> Path:
    path = Path(traces_root) / agent / suite / f"{case_id}.json"
    if path.is_file():
        return path
    raise FileNotFoundError(
        f"No trace at {path}. Capture first, e.g.\n"
        f"  pytest tests/{agent}/test_sanity.py -v -s"
    )
