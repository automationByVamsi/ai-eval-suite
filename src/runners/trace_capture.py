"""
Shared per-test-case capture step: invoke one agent, write one trace file.
Used by scripts/capture_traces.py (always overwrites) and scripts/run_tests.py
(overwrites or skips depending on --mode) so the write path only exists once.
"""

import json
import time
from pathlib import Path

from src.models.test_case import TestCase
from src.runners.factories import AgentFactory


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
