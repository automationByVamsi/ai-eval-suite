"""
Knowledge Agent — stage1 evaluation.

  run_case (live) → prepare_stage1 (parse + det) → optional evaluate judges

  pytest tests/knowledge_agent/test_stage1_eval.py -v
  RUN_JUDGES=1 pytest ...   # also run suite judges (needs CORTEX)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.runners.case_runner import load_cases, run_case
from src.runners.evaluate import evaluate
from tests.knowledge_agent.ka_eval import prepare_stage1

AGENT = "knowledge_agent"
DATA_SUITE = "sanity"
METRICS_SUITE = "stage1_query_rewrite"
OUTPUT_DIR = Path("outputs/traces")

CASES = load_cases(AGENT, DATA_SUITE)
CASE_IDS = [c["test_case_id"] for c in CASES]


class TestKnowledgeAgentStage1Eval:
    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_stage1_after_live_capture(self, case: dict):
        try:
            capture = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR)
        except AgentInvocationError as exc:
            pytest.skip(f"ADK not reachable: {exc}")

        assert capture.saved_path and capture.saved_path.exists()

        _parsed, det, response = prepare_stage1(str(capture.saved_path), case)
        failed_det = [(c.name, c.reason) for c in det if not c.passed]
        assert not failed_det, failed_det

        if os.environ.get("RUN_JUDGES") == "1":
            judges = evaluate(AGENT, METRICS_SUITE, case, response)
            failed_j = [(c.name, c.reason) for c in judges.failed]
            assert not failed_j, failed_j
