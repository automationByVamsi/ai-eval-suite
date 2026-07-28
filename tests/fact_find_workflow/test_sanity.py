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
from src.parsers.fact_find_workflow import enrich, extract
from src.runners.case_runner import eval_mode, judges_enabled, load_cases, run_case
from src.runners.evaluate import evaluate
from tests.fact_find_workflow.ff_eval import prepare_for_judges, suite_for_case

AGENT = "fact_find_workflow"
DATA_SUITE = "sanity"
METRICS_SUITE = "sanity"
OUTPUT_DIR = Path("outputs/traces")

CASES = load_cases(AGENT, DATA_SUITE)
CASE_IDS = [c["test_case_id"] for c in CASES]


def _assert_deterministic(case: dict, raw: dict, complaint_ref: str) -> None:
    """Layer-1 checks from the FF parser view (no LLM)."""
    view = extract(raw, complaint_ref=complaint_ref)
    expected = case.get("expected") or {}
    path = expected.get("path")

    assert view.answer.strip(), "deterministic: empty agent answer"

    for kw in expected.get("keywords") or []:
        assert str(kw).lower() in view.answer.lower(), (
            f"deterministic: keyword {kw!r} not found in answer"
        )

    if path == "success":
        assert view.looks_like_summary, "deterministic: expected FactFind summary"
        assert not view.is_invalid_message, "deterministic: unexpected InvalidComplaintId"
        assert not view.validation_failed, "deterministic: validation_failed on success path"
        assert complaint_ref in view.answer or view.complaint_ref == complaint_ref

        want_party = expected.get("party_id")
        if want_party and view.party_id:
            assert view.party_id == str(want_party), (
                f"deterministic: party_id={view.party_id!r}, expected {want_party!r}"
            )

        # Tools only when the trace has functionCall events (full live / org shape)
        if view.tool_names:
            assert len(view.tool_names) >= 1, "deterministic: expected at least one tool"

    if path == "invalid_complaint":
        assert view.validation_failed or view.is_invalid_message, (
            "deterministic: expected invalid-complaint signals"
        )
        assert not view.looks_like_summary, (
            "deterministic: invalid path should not look like a summary"
        )


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
        raw = result.response.raw_output if isinstance(result.response.raw_output, dict) else {}
        _assert_deterministic(case, raw, complaint_ref)

        response = enrich(result.response, complaint_ref=complaint_ref)
        assert response.metadata.get("complaint_ref") or complaint_ref

        if judges_enabled():
            response = prepare_for_judges(case, response)
            suite = suite_for_case(case)
            judges = evaluate(AGENT, suite, case, response)
            failed = [(j.name, j.score, j.reason) for j in judges.failed]
            assert not failed, failed
