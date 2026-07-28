"""
Knowledge Agent — sanity capture + optional suite judges.

  EVAL_MODE=live  (default) → call ADK, save trace, assert / evaluate
  EVAL_MODE=cache           → load outputs/traces/... , assert / evaluate

  pytest tests/knowledge_agent/test_sanity.py -v -s
  EVAL_MODE=cache pytest tests/knowledge_agent/test_sanity.py -v -s
  RUN_JUDGES=true EVAL_MODE=cache pytest tests/knowledge_agent/test_sanity.py -v -s
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.parsers.knowledge_agent import enrich
from src.runners.case_runner import eval_mode, judges_enabled, load_cases, run_case
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
    def test_run_case(self, case: dict):
        mode = eval_mode()
        try:
            result = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR, mode=mode)
        except AgentInvocationError as exc:
            pytest.skip(f"ADK not reachable: {exc}")
        except FileNotFoundError as exc:
            pytest.skip(str(exc))

        assert result.test_case_id == case["test_case_id"]
        assert result.saved_path and result.saved_path.exists()
        assert result.mode == mode

        question = case["input"]["question"]
        response = enrich(result.response, question=question)
        assert response.answer, "empty agent answer"

        for kw in case.get("expected", {}).get("keywords") or []:
            assert kw.lower() in response.answer.lower(), (
                f"expected keyword {kw!r} not found in answer"
            )

        if judges_enabled():
            judges = evaluate(AGENT, METRICS_SUITE, case, response)
            failed = [(j.name, j.score, j.reason) for j in judges.failed]
            assert not failed, failed
