"""Shared sanity fixtures: load + validate cases once (not as separate tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.runners.case_runner import load_cases, validate_case_envelope

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
