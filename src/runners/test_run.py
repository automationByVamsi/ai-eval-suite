"""
Core "ensure traces exist per mode, then evaluate" flow - shared by
scripts/run_tests.py (CLI) and tests/knowledge_agent/test_demo_end_to_end.py
(pytest), so the mode semantics only exist once.
"""

from pathlib import Path

from src.core.config import load_stage_config
from src.models.evaluation_result import StageEvaluationResult
from src.models.test_case import TestCase
from src.runners.factories import AgentFactory, MetricFactory
from src.runners.stage_evaluation import evaluate_traces
from src.runners.stage_registry import load_evaluator_class
from src.runners.trace_capture import capture_one

VALID_MODES = ("cache", "incremental", "refresh")


def run_tests(
    agent: str,
    tag: str,
    stage: str,
    mode: str,
    configs: str = "configs",
    output: str = "outputs/dashboard",
) -> list[StageEvaluationResult]:
    """
    mode="cache"        never call the agent - reuse traces only, raise if
                         any test case has no captured trace
    mode="incremental"  call the agent only for test cases missing a trace
    mode="refresh"       call the agent for every test case, overwrite traces

    Every mode always (re-)runs both deterministic and judge validations on
    whatever ends up in the trace directory.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")

    testdata_dir = Path("testdata") / agent / tag
    trace_dir = Path("outputs/traces") / agent / tag
    trace_dir.mkdir(parents=True, exist_ok=True)

    test_case_files = sorted(testdata_dir.glob("*.json"))
    if not test_case_files:
        raise FileNotFoundError(f"No test cases found under {testdata_dir}")
    test_cases = [TestCase.from_json_file(str(p)) for p in test_case_files]

    if mode == "cache":
        missing = [tc.test_case_id for tc in test_cases if not (trace_dir / f"{tc.test_case_id}.json").exists()]
        if missing:
            raise FileNotFoundError(
                f"Cache mode: no captured trace for {missing} under {trace_dir}. "
                f"Use mode='incremental' (capture only what's missing) or mode='refresh' "
                f"(recapture everything) first."
            )
    else:
        agent_factory = AgentFactory(f"{configs}/agents.yaml")
        for test_case in test_cases:
            trace_path = trace_dir / f"{test_case.test_case_id}.json"
            if mode == "incremental" and trace_path.exists():
                print(f"Cached {test_case.test_case_id} -> {trace_path}")
                continue
            out_path, latency_ms = capture_one(agent_factory, test_case, trace_dir)
            print(f"Captured {test_case.test_case_id} -> {out_path} ({latency_ms:.0f}ms)")

    evaluator_cls = load_evaluator_class(agent, stage)
    stage_config = load_stage_config(agent, stage, base_dir=f"{configs}/evaluations")
    metric_factory = MetricFactory(f"{configs}/cortex.yaml")
    evaluator = evaluator_cls(metric_factory, stage_config)

    trace_files = sorted(trace_dir.glob("*.json"))
    return evaluate_traces(evaluator, trace_files, output)
