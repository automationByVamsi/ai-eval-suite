"""
Shared capture flow for any agent / data suite.

  load_cases(agent, data_suite)  → list of case dicts from testdata/
  run_case(agent, case, data_suite) → invoke ADK, save under outputs/, return CaseRun

Pytest owns validation; this module only arrange → act → store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.clients.adk_client import AdkClient, load_replay_response
from src.models.agent_response import AgentResponse


@dataclass(frozen=True)
class CaseRun:
    """Result of running one case (enough for the test to assert)."""

    agent_name: str
    data_suite: str
    case: dict[str, Any]
    response: AgentResponse
    saved_path: Path | None

    @property
    def test_case_id(self) -> str:
        return str(self.case.get("test_case_id") or "unknown")


def load_cases(
    agent_name: str,
    data_suite: str,
    *,
    testdata_root: str | Path = "testdata",
) -> list[dict[str, Any]]:
    """
    Load cases from testdata/<agent_name>/<data_suite>/.

    Supports:
      - one JSON per scenario (has test_case_id + input)
      - one JSON with { "cases": [ {...}, ... ] }
    """
    folder = Path(testdata_root) / agent_name / data_suite
    if not folder.is_dir():
        raise FileNotFoundError(f"No test data folder: {folder}")

    cases: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object in {path}")

        if isinstance(data.get("cases"), list):
            for i, item in enumerate(data["cases"]):
                if not isinstance(item, dict):
                    raise ValueError(f"cases[{i}] in {path} must be an object")
                cases.append(_normalize_case(item, default_id=f"{path.stem}_{i}"))
        elif "input" in data or "test_case_id" in data:
            cases.append(_normalize_case(data, default_id=path.stem))
        # else: skip unrelated JSON in the folder

    if not cases:
        raise FileNotFoundError(f"No test cases found under {folder}")
    return cases


def run_case(
    agent_name: str,
    case: dict[str, Any],
    data_suite: str,
    *,
    output_dir: str | Path = "outputs",
    mode: str = "live",
    agents_path: str | Path = "configs/agents.yaml",
) -> CaseRun:
    """
    Invoke one case and save the full agent JSON.

    Output path: <output_dir>/<agent_name>/<data_suite>/<test_case_id>.json
    mode: "live" (call ADK) | "replay" (read that output path; no network)
    """
    case_id = str(case.get("test_case_id") or "run")
    save_dir = Path(output_dir) / agent_name / data_suite
    save_path = save_dir / f"{case_id}.json"

    if mode == "replay":
        response = load_replay_response(save_path)
        return CaseRun(
            agent_name=agent_name,
            data_suite=data_suite,
            case=case,
            response=response,
            saved_path=save_path if save_path.exists() else None,
        )

    client = AdkClient.from_agent_name(agent_name, agents_path=agents_path)
    user_text = client.build_user_text(case.get("input") or {})
    response, saved = client.get_agent_output(
        user_text,
        case_id=case_id,
        save_dir=save_dir,
    )
    return CaseRun(
        agent_name=agent_name,
        data_suite=data_suite,
        case=case,
        response=response,
        saved_path=saved,
    )


def _normalize_case(raw: dict[str, Any], *, default_id: str) -> dict[str, Any]:
    case = dict(raw)
    case.setdefault("test_case_id", default_id)
    case.setdefault("input", {})
    case.setdefault("expected", {})
    return case
