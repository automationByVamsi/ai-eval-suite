"""
Find the test cases of a suite.

Every *.json under the suite's testdata folder is read, sub-folders included (anything whose
path contains a folder or file starting with _ is skipped). A file holds one case, or several
as {"cases": [...]}. A case looks like:

    {
      "test_case_id": "TC_001",                  # defaults to the file name
      "input":    {"question": "..."},           # must contain the agent's input_field
      "expected": {"expected_answer": "...", "keywords": ["..."]},   # all optional
      "metadata": {...}                          # optional, free-form
    }

A suite's `only:` in agent.yaml keeps matching cases, e.g. only: {metadata.approval_status: APPROVED}.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.agent_config import Agent, Suite
from src.core.exceptions import ConfigError


def load_cases(agent: Agent, suite: Suite) -> list[dict[str, Any]]:
    """All cases of a suite, validated. Raises ConfigError if there are none or IDs repeat."""
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
    """dotted(case, "metadata.approval_status") -> case["metadata"]["approval_status"], or None."""
    for part in path.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data
