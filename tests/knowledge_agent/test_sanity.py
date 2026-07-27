"""
Knowledge Agent — sanity capture + optional suite judges.

  load_cases → run_case → assert answer
  RUN_JUDGES=1 → evaluate("sanity")  # also publishes to Streamlit dashboard

  pytest tests/knowledge_agent/test_sanity.py -v -s
  RUN_JUDGES=1 pytest tests/knowledge_agent/test_sanity.py -v -s
  streamlit run scripts/dashboard_app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.runners.case_runner import load_cases, run_case
from src.runners.evaluate import evaluate

AGENT = "knowledge_agent"
DATA_SUITE = "sanity"
METRICS_SUITE = "sanity"
OUTPUT_DIR = Path("outputs/traces")

CASES = load_cases(AGENT, DATA_SUITE)
CASE_IDS = [c["test_case_id"] for c in CASES]


class TestKnowledgeAgentSanity:
    def test_cases_loaded(self):
        assert CASES, "expected sanity cases for knowledge_agent"
        assert "TC_001" in CASE_IDS
        assert "TC_002" in CASE_IDS

    def test_every_case_has_required_input(self):
        for case in CASES:
            assert case["test_case_id"]
            assert case["input"], f"{case['test_case_id']}: input required"
            assert "question" in case["input"]
            assert isinstance(case.get("expected", {}), dict)

    def test_sanity_suite_resolves_from_catalog(self):
        from src.core.config import resolve_suite_metrics

        cfgs = resolve_suite_metrics(AGENT, METRICS_SUITE)
        names = [c["name"] for c in cfgs]
        assert names == ["relevance"]
        assert cfgs[0]["type"] == "relevance"

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_run_case_live(self, case: dict):
        try:
            result = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR)
        except AgentInvocationError as exc:
            pytest.skip(f"ADK not reachable: {exc}")

        assert result.test_case_id == case["test_case_id"]
        assert result.saved_path and result.saved_path.exists()
        assert result.response.answer, "empty agent answer"

        for kw in case.get("expected", {}).get("keywords") or []:
            assert kw.lower() in result.response.answer.lower(), (
                f"expected keyword {kw!r} not found in answer"
            )

        if os.environ.get("RUN_JUDGES") == "1":
            judges = evaluate(AGENT, METRICS_SUITE, case, result.response)
            failed = [(j.name, j.score, j.reason) for j in judges.failed]
            assert not failed, failed
