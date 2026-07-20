"""
Shared per-test-case capture step: invoke one agent, write one trace file.
Used by scripts/capture_traces.py and tests/base_agent_test.py.

Modes:
  cache        reuse traces only — fail if any case is missing one
  incremental  capture only cases with no trace yet
  refresh      capture every case, overwrite existing traces
"""

import json
import time
from pathlib import Path

from src.models.test_case import TestCase
from src.runners.factories import AgentFactory

VALID_CAPTURE_MODES = ("cache", "incremental", "refresh")


def capture_one(agent_factory: AgentFactory, test_case: TestCase, trace_dir: Path) -> tuple[Path, float]:
    agent = agent_factory.create(test_case.agent_name)

    start = time.perf_counter()
    response = agent.invoke({**test_case.input, "_test_case_id": test_case.test_case_id})
    latency_ms = (time.perf_counter() - start) * 1000

    trace = {
        "test_case": test_case.model_dump(),
        "raw_output": response.raw_output if response.raw_output is not None else response.model_dump(),
    }
    out_path = trace_dir / f"{test_case.test_case_id}.json"
    out_path.write_text(json.dumps(trace, indent=2, default=str))
    return out_path, latency_ms


def ensure_traces(
    test_cases: list[TestCase],
    trace_dir: Path,
    mode: str,
    agent_factory: AgentFactory,
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
            capture_one(agent_factory, test_case, trace_dir)

    return [trace_dir / f"{tc.test_case_id}.json" for tc in test_cases]
