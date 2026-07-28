"""
Fact Find Workflow — sanity capture + optional suite judges.

  EVAL_MODE=live  (default) → call ADK, save trace, assert / evaluate
  EVAL_MODE=cache           → load outputs/traces/... , assert / evaluate

  pytest tests/fact_find_workflow/test_sanity.py -v -s
  EVAL_MODE=cache pytest tests/fact_find_workflow/test_sanity.py -v -s
  RUN_JUDGES=true EVAL_MODE=cache pytest tests/fact_find_workflow/test_sanity.py -v -s
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.parsers.fact_find_workflow import enrich
from src.runners.case_runner import eval_mode, judges_enabled, load_cases, run_case
from src.runners.evaluate import evaluate
from tests.fact_find_workflow.ff_eval import prepare_for_judges, suite_for_case

AGENT = "fact_find_workflow"
DATA_SUITE = "sanity"
METRICS_SUITE = "sanity"
OUTPUT_DIR = Path("outputs/traces")

CASES = load_cases(AGENT, DATA_SUITE)
CASE_IDS = [c["test_case_id"] for c in CASES]


class TestFactFindWorkflowSanity:
    def test_cases_loaded(self):
        assert CASES, "expected sanity cases for fact_find_workflow"
        assert "TC_001" in CASE_IDS
        assert "TC_002" in CASE_IDS

    def test_every_case_has_required_input(self):
        for case in CASES:
            assert case["test_case_id"]
            assert case["input"]
            assert "complaint_ref" in case["input"]
            assert isinstance(case.get("expected", {}), dict)

    def test_sanity_suite_resolves_from_catalog(self):
        from src.core.config import resolve_suite_metrics

        cfgs = resolve_suite_metrics(AGENT, METRICS_SUITE)
        names = [c["name"] for c in cfgs]
        assert names == ["relevance"]
        assert cfgs[0]["type"] == "relevance"

    def test_path_suites_resolve_from_catalog(self):
        from src.core.config import resolve_suite_metrics

        gate = [c["name"] for c in resolve_suite_metrics(AGENT, "gate_validation")]
        assert gate == ["validation_message_clarity", "relevance"]

        summary = [c["name"] for c in resolve_suite_metrics(AGENT, "summary_vs_aggregate")]
        assert "faithfulness" in summary
        assert "support_needs_fidelity" in summary
        assert "complaint_account_association" in summary

    def test_prepare_for_judges_attaches_aggregate_context(self):
        from src.models.agent_response import AgentResponse

        case = next(c for c in CASES if c["test_case_id"] == "TC_001")
        bare = AgentResponse(answer="Customer FactFind Summary for NC10010556")
        enriched = prepare_for_judges(case, bare)
        assert enriched.context, "expected retrieval_context chunks from aggregate"
        assert "source_document" in enriched.metadata
        assert "NC10010556" in enriched.metadata["source_document"]

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

        complaint_ref = case["input"]["complaint_ref"]
        response = enrich(result.response, complaint_ref=complaint_ref)
        assert response.answer, "empty agent answer"
        for kw in case.get("expected", {}).get("keywords") or []:
            assert kw.lower() in response.answer.lower(), (
                f"expected keyword {kw!r} not found in answer"
            )

        # Path-shaped deterministic hints from the parser
        path = (case.get("expected") or {}).get("path")
        if path == "invalid_complaint":
            assert response.metadata.get("validation_failed") or response.metadata.get(
                "is_invalid_complaint_message"
            )
        if path == "success":
            assert response.metadata.get("looks_like_summary")

        if judges_enabled():
            response = prepare_for_judges(case, response)
            suite = suite_for_case(case)
            judges = evaluate(AGENT, suite, case, response)
            failed = [(j.name, j.score, j.reason) for j in judges.failed]
            assert not failed, failed
