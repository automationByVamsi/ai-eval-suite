"""
End-to-end demo, written to be read top-to-bottom during a live walkthrough.

Every step - decide what to (re)capture per mode, trigger the agent, save
its raw response, run both validation layers, publish for the dashboard -
is inlined here explicitly, rather than delegated to scripts/run_tests.py's
shared helpers (src/runners/test_run.py, trace_capture.py, stage_evaluation.py).
That's a deliberate choice for THIS file only: the point of a demo is that
someone watching can see exactly what happens at each step without having to
open three other files. The actual regression suite
(test_stage1_deterministic.py, etc.) and the CLI (scripts/run_tests.py) DO
use those shared helpers - this file duplicating the flow doesn't change
that; it's a teaching aid, not the source of truth for the mode logic.

Controlled by the DEMO_MODE env var (defaults to "cache" - the fastest,
network-free mode):

    DEMO_MODE=cache       pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s
    DEMO_MODE=incremental pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s
    DEMO_MODE=refresh     pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s

or via the Makefile: `make demo-cache` / `make demo-incremental` / `make demo-refresh`.
(-s is required so the printed steps below are actually visible - pytest
hides stdout on a pass by default.)

  cache        never calls the agent - reuses whatever's already captured.
               Fails loudly if any test case has no captured trace.
  incremental  calls the agent only for test cases with no captured trace
               yet; everything already captured is reused untouched.
  refresh      calls the agent for every test case, overwriting all traces.
"""

import json
import os
import time
from pathlib import Path

from src.core.config import load_stage_config
from src.evaluators.knowledge_agent.stage1_query_rewrite import Stage1QueryRewriteEvaluator
from src.models.test_case import TestCase
from src.runners.factories import AgentFactory, MetricFactory

AGENT = "knowledge_agent"
TAG = "sanity"
STAGE = "stage1_query_rewrite"
VALID_MODES = ("cache", "incremental", "refresh")

TESTDATA_DIR = Path("testdata") / AGENT / TAG
TRACE_DIR = Path("outputs/traces") / AGENT / TAG
DASHBOARD_DIR = Path("outputs/dashboard")


def test_demo_trigger_capture_validate_and_publish_to_dashboard():
    mode = os.environ.get("DEMO_MODE", "cache")
    assert mode in VALID_MODES, f"DEMO_MODE must be one of {VALID_MODES}, got {mode!r}"
    print(f"\n=== Demo run: agent={AGENT} stage={STAGE} mode={mode} ===")

    # --- Step 1: load every test case for this agent/tag off disk ---
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    test_case_files = sorted(TESTDATA_DIR.glob("*.json"))
    assert test_case_files, f"No test cases found under {TESTDATA_DIR}"
    test_cases = [TestCase.from_json_file(str(p)) for p in test_case_files]
    print(f"Step 1: loaded {len(test_cases)} test case(s): {[tc.test_case_id for tc in test_cases]}")

    # --- Step 2: trigger the agent and save its response, per the chosen mode ---
    agent_factory = AgentFactory("configs/agents.yaml")
    for test_case in test_cases:
        trace_path = TRACE_DIR / f"{test_case.test_case_id}.json"
        already_captured = trace_path.exists()

        if mode == "cache":
            assert already_captured, (
                f"cache mode: no captured trace for {test_case.test_case_id} at {trace_path}. "
                f"Run with DEMO_MODE=incremental or DEMO_MODE=refresh first."
            )
            print(f"  [cache]       {test_case.test_case_id}: reusing {trace_path}")
            continue

        if mode == "incremental" and already_captured:
            print(f"  [incremental] {test_case.test_case_id}: already captured, skipping the agent call")
            continue

        # mode == "refresh", or mode == "incremental" with nothing captured yet:
        # actually call the agent.
        agent = agent_factory.create(test_case.agent_name)
        start = time.perf_counter()
        response = agent.invoke({**test_case.input, "_test_case_id": test_case.test_case_id})
        latency_ms = (time.perf_counter() - start) * 1000

        trace = {
            "test_case": test_case.model_dump(),
            "raw_output": response.raw_output if response.raw_output is not None else response.model_dump(),
        }
        trace_path.write_text(json.dumps(trace, indent=2, default=str))
        print(f"  [{mode}] {test_case.test_case_id}: captured live in {latency_ms:.0f}ms -> {trace_path}")

    # --- Step 3: build the stage evaluator - deterministic + judge checks are
    #             both driven by configs/evaluations/knowledge_agent/stage1_query_rewrite.yaml,
    #             nothing about which metrics run is hardcoded here ---
    stage_config = load_stage_config(AGENT, STAGE)
    metric_factory = MetricFactory("configs/cortex.yaml")
    evaluator = Stage1QueryRewriteEvaluator(metric_factory, stage_config)
    print(f"Step 3: built {type(evaluator).__name__} for stage config {stage_config}")

    # --- Step 4: run both validation layers against every captured trace,
    #             and publish each result for Streamlit to pick up ---
    all_deterministic_passed = True
    for trace_path in sorted(TRACE_DIR.glob("*.json")):
        result = evaluator.evaluate(str(trace_path))
        result.print_summary()

        det_passed = sum(c.passed for c in result.deterministic_results)
        judge_passed = sum(m.passed for m in result.metric_results)
        print(
            f"  [{'PASS' if result.passed else 'FAIL'}] {result.test_case_id}: "
            f"deterministic {det_passed}/{len(result.deterministic_results)}, "
            f"judge {judge_passed}/{len(result.metric_results)}"
        )

        agent_dir = DASHBOARD_DIR / (result.agent_name or "unknown_agent")
        agent_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = agent_dir / f"{result.stage_name}__{result.test_case_id}.json"
        dashboard_path.write_text(result.model_dump_json(indent=2))
        print(f"  published -> {dashboard_path}")

        if not all(c.passed for c in result.deterministic_results):
            all_deterministic_passed = False

    # Layer 1 (deterministic) is fast, offline, and has no excuse to fail on a
    # known-good trace - a failure there is a real regression. Layer 2 (judge)
    # depends on a live CORTEX endpoint, so it's reported above, not asserted:
    # a network hiccup during a live demo shouldn't read as "the agent got worse."
    assert all_deterministic_passed, "One or more test cases failed a deterministic check - see output above"

    print(f"\nStep 4 done - view results with: streamlit run scripts/dashboard_app.py")
