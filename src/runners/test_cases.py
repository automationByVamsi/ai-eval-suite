"""
Load a suite's test cases: every *.json under its testdata folder (paths with a `_` part are skipped).
A file holds one case or {"cases": [...]}; the suite's `only:` filter keeps matching cases.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.agent_config import Agent, Suite
from src.core.exceptions import ConfigError


def load_cases(agent: Agent, suite: Suite) -> list[dict[str, Any]]:
    """Return the suite's validated cases. Raises ConfigError if there are none or IDs repeat."""
    if not suite.testdata.is_dir():
        raise ConfigError(f"Test data folder not found: {suite.testdata} (generated suites: run make goldens first)")
    cases: list[dict[str, Any]] = []
    for path in sorted(suite.testdata.rglob("*.json")):
        if any(part.startswith("_") for part in path.relative_to(suite.testdata).parts):
            continue
        data = json.loads(path.read_text())
        many = "cases" in data
        for i, case in enumerate(data["cases"] if many else [data]):
            case.setdefault("test_case_id", f"{path.stem}_{i}" if many else path.stem)
            case.setdefault("expected", {})
            if agent.input_field not in (case.get("input") or {}):
                raise ConfigError(f"{path}: input.{agent.input_field} is required for {agent.name}")
            if all(dotted(case, key) == value for key, value in suite.only.items()):
                cases.append(case)
    if not cases:
        only = f" matching only: {suite.only}" if suite.only else ""
        raise ConfigError(f"No test cases in {suite.testdata}{only}")
    ids = [c["test_case_id"] for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"Duplicate test_case_id in {suite.testdata}: {duplicates}")
    return cases


def dotted(data: dict[str, Any], path: str) -> Any:
    """Return the value at a dotted path like "metadata.status", or None."""
    for part in path.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data
