"""Shared sanity fixtures: load + validate cases once (not as separate tests)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.reporting.persist import publish_suite_result
from src.runners.case_runner import load_cases, validate_case_envelope
from src.runners.evaluate import CheckResult

OUTPUT_DIR = Path("outputs/traces")
DATA_SUITE = "sanity"


def load_sanity_cases(
    agent: str,
    *,
    required_input_keys: list[str],
) -> list[dict[str, Any]]:
    """
    Load testdata/<agent>/sanity and fail fast if envelopes are wrong.
    Call from agent conftest — not as pytest test methods.
    """
    cases = load_cases(agent, DATA_SUITE)
    assert cases, f"expected sanity cases under testdata/{agent}/{DATA_SUITE}"

    for case in cases:
        cid = case.get("test_case_id", "?")
        validate_case_envelope(case, source=cid)
        inp = case.get("input") or {}
        for key in required_input_keys:
            assert key in inp, f"{cid}: input missing {key!r}"
        assert isinstance(case.get("expected", {}), dict), f"{cid}: expected must be an object"

        # Fact Find success cases need the aggregate file on disk for judges
        rel = (case.get("expected") or {}).get("aggregated_payload_path")
        if rel:
            path = Path(rel)
            assert path.is_file(), f"{cid}: aggregated payload missing: {path}"

    return cases


def check(name: str, passed: bool, reason: str = "") -> CheckResult:
    """One named deterministic check for dashboard + pytest."""
    return CheckResult(name=name, passed=passed, reason="" if passed else reason)


def publish_case(
    *,
    agent: str,
    suite: str,
    case: dict[str, Any],
    response: AgentResponse,
    deterministic: list[CheckResult] | None = None,
    judges: list[Any] | None = None,
    result_fields: dict[str, Any] | None = None,
) -> Path | None:
    """Write det + judges to the Streamlit dashboard (no-op if DASHBOARD_DISABLE=1)."""
    if os.environ.get("DASHBOARD_DISABLE") == "1":
        return None
    return publish_suite_result(
        agent_name=agent,
        suite=suite,
        case=case,
        response=response,
        deterministic=deterministic or [],
        judges=judges or [],
        result_fields=result_fields,
    )


def assert_all_passed(checks: list[CheckResult], *, label: str) -> None:
    failed = [(c.name, c.score, c.reason) for c in checks if not c.passed]
    assert not failed, f"{label}: {failed}"
