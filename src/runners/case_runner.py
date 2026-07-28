"""
Shared case flow for any agent / data suite.

  load_cases(agent, data_suite) → list of case dicts from testdata/
  run_case(...) → live ADK *or* load cached trace (EVAL_MODE)

Modes (env EVAL_MODE, or mode= kwarg):
  live  — call agent, save under outputs/traces/, return CaseRun (default)
  cache — load existing trace from outputs/traces/, no ADK call

Case envelope (same for every agent):
  - test_case_id: required
  - input: required, non-empty object (agent-specific keys inside)
  - expected: optional
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.clients.adk_client import AdkClient
from src.models.agent_response import AgentResponse
from src.parsers import adk_parser


@dataclass(frozen=True)
class CaseRun:
    """Result of running one case (enough for the test to assert)."""

    agent_name: str
    data_suite: str
    case: dict[str, Any]
    response: AgentResponse
    saved_path: Path | None
    mode: str = "live"

    @property
    def test_case_id(self) -> str:
        return str(self.case.get("test_case_id") or "unknown")


def eval_mode(explicit: str | None = None) -> str:
    """Resolve live|cache from kwarg or EVAL_MODE (default: live)."""
    mode = (explicit or os.environ.get("EVAL_MODE") or "live").strip().lower()
    if mode not in ("live", "cache"):
        raise ValueError(f"EVAL_MODE must be 'live' or 'cache', got {mode!r}")
    return mode


def judges_enabled() -> bool:
    """True when RUN_JUDGES=true (also accepts 1/yes/on)."""
    return os.environ.get("RUN_JUDGES", "").strip().lower() in {"1", "true", "yes", "on"}


def trace_path(
    agent_name: str,
    data_suite: str,
    case_id: str,
    *,
    output_dir: str | Path = "outputs/traces",
) -> Path:
    return Path(output_dir) / agent_name / data_suite / f"{case_id}.json"


def validate_case_envelope(case: dict[str, Any], *, source: str = "case") -> None:
    """Shared rules for every agent: id + non-empty input; expected is optional."""
    if not str(case.get("test_case_id") or "").strip():
        raise ValueError(f"{source}: test_case_id is required")
    inp = case.get("input")
    if not isinstance(inp, dict) or not inp:
        raise ValueError(f"{source}: input must be a non-empty object")


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
                case = _normalize_case(item, default_id=f"{path.stem}_{i}")
                validate_case_envelope(case, source=str(path))
                cases.append(case)
        elif "input" in data or "test_case_id" in data:
            case = _normalize_case(data, default_id=path.stem)
            validate_case_envelope(case, source=str(path))
            cases.append(case)

    if not cases:
        raise FileNotFoundError(f"No test cases found under {folder}")
    return cases


def load_cached_case(
    agent_name: str,
    case: dict[str, Any],
    data_suite: str,
    *,
    output_dir: str | Path = "outputs/traces",
) -> CaseRun:
    """Load a previously saved ADK JSON and rebuild AgentResponse."""
    validate_case_envelope(case)
    case_id = str(case["test_case_id"])
    path = trace_path(agent_name, data_suite, case_id, output_dir=output_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"No cached trace at {path}. Run once with EVAL_MODE=live first."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    raw = _unwrap_raw(data)
    response = AgentResponse(
        answer=adk_parser.extract_answer(raw),
        raw_output=raw,
        context=adk_parser.extract_context(raw),
        events=adk_parser.extract_events(raw),
        session_id=adk_parser.extract_session_id(raw),
        latency_ms=adk_parser.extract_latency_ms(raw),
    )
    return CaseRun(
        agent_name=agent_name,
        data_suite=data_suite,
        case=case,
        response=response,
        saved_path=path,
        mode="cache",
    )


def run_case(
    agent_name: str,
    case: dict[str, Any],
    data_suite: str,
    *,
    output_dir: str | Path = "outputs/traces",
    agents_path: str | Path = "configs/agents.yaml",
    mode: str | None = None,
) -> CaseRun:
    """
    live  → ADK invoke, save JSON, return CaseRun
    cache → load existing JSON under output_dir (no ADK)
    """
    mode = eval_mode(mode)
    if mode == "cache":
        return load_cached_case(
            agent_name, case, data_suite, output_dir=output_dir
        )

    validate_case_envelope(case)
    case_id = str(case["test_case_id"])
    save_dir = Path(output_dir) / agent_name / data_suite

    client = AdkClient.from_agent_name(agent_name, agents_path=agents_path)
    field = client.message_field
    if field not in (case.get("input") or {}):
        raise ValueError(
            f"Case {case_id}: input missing '{field}' "
            f"(required by agents.yaml message_field for {agent_name})"
        )
    user_text = client.build_user_text(case["input"])
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
        mode="live",
    )


def _unwrap_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Accept flat AdkClient saves or wrapped { raw_output: {...} } files."""
    inner = data.get("raw_output")
    if isinstance(inner, dict) and (
        "agentOutput" in inner or "raw_events" in inner or "sessionId" in inner
    ):
        return inner
    return data


def _normalize_case(raw: dict[str, Any], *, default_id: str) -> dict[str, Any]:
    case = dict(raw)
    case.setdefault("test_case_id", default_id)
    if "expected" in case and case["expected"] is None:
        case["expected"] = {}
    if "input" not in case:
        case["input"] = {}
    return case
