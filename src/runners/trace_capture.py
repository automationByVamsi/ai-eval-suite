"""
Shared per-test-case capture step: invoke one ADK agent, write one trace file.
Used by scripts/capture_traces.py and tests/base_agent_test.py.

Modes:
  cache        reuse traces only — fail if any case is missing one
  incremental  capture only cases with no trace yet
  refresh      capture every case, overwrite existing traces
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.clients.adk_client import invoke_agent
from src.models.test_case import TestCase

VALID_CAPTURE_MODES = ("cache", "incremental", "refresh")


def capture_one(
    test_case: TestCase,
    trace_dir: Path,
    *,
    agents_path: str = "configs/agents.yaml",
) -> tuple[Path, float]:
    """Live ADK call for one case; write {test_case, raw_output} under trace_dir."""
    start = time.perf_counter()
    response = invoke_agent(
        test_case.agent_name,
        {**test_case.input, "_test_case_id": test_case.test_case_id},
        mode="live",
        trace_dir=None,  # we wrap + write below for a stable on-disk shape
        agents_path=agents_path,
    )
    latency_ms = (time.perf_counter() - start) * 1000

    # Prefer latency measured by the client when present
    if response.latency_ms is not None:
        latency_ms = response.latency_ms

    trace = {
        "test_case": test_case.model_dump(),
        "raw_output": response.raw_output if response.raw_output is not None else response.model_dump(),
    }
    out_path = trace_dir / f"{test_case.test_case_id}.json"
    trace_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    return out_path, latency_ms


def ensure_traces(
    test_cases: list[TestCase],
    trace_dir: Path,
    mode: str,
    *,
    agents_path: str = "configs/agents.yaml",
) -> list[Path]:
    """
    Make sure a trace file exists for every test case (per mode), then return
    the paths. Does not run any evaluations — capture only.
    """
    if mode not in VALID_CAPTURE_MODES:
        raise ValueError(f"mode must be one of {VALID_CAPTURE_MODES}, got {mode!r}")

    trace_dir.mkdir(parents=True, exist_ok=True)

    if mode == "cache":
        missing = [tc.test_case_id for tc in test_cases if not (trace_dir / f"{tc.test_case_id}.json").exists()]
        if missing:
            raise FileNotFoundError(
                f"Cache mode: no captured trace for {missing} under {trace_dir}. "
                f"Use mode='incremental' or mode='refresh' first."
            )
    else:
        for test_case in test_cases:
            trace_path = trace_dir / f"{test_case.test_case_id}.json"
            if mode == "incremental" and trace_path.exists():
                continue
            capture_one(test_case, trace_dir, agents_path=agents_path)

    return [trace_dir / f"{tc.test_case_id}.json" for tc in test_cases]
