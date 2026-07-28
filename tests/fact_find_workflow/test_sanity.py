"""
Fact Find Workflow — run + evaluate only.

Setup (cases / input checks / aggregate paths) lives in conftest.py.

  EVAL_MODE=live|cache
  RUN_JUDGES=true   → also run CORTEX suite judges

  make test-ff-sanity
  make test-ff-sanity-judges
"""

from __future__ import annotations

from src.core.exceptions import AgentInvocationError
from src.parsers.fact_find_workflow import enrich, extract
from src.runners.case_runner import eval_mode, judges_enabled, run_case
from src.runners.evaluate import evaluate
from tests.fact_find_workflow.conftest import AGENT, METRICS_SUITE
from tests.fact_find_workflow.ff_eval import prepare_for_judges
from tests.support.sanity import DATA_SUITE, OUTPUT_DIR


def _assert_deterministic(case: dict, raw: dict, complaint_ref: str) -> None:
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
        if view.tool_names:
            assert len(view.tool_names) >= 1

    if path == "invalid_complaint":
        assert view.validation_failed or view.is_invalid_message, (
            "deterministic: expected invalid-complaint signals"
        )
        assert not view.looks_like_summary, (
            "deterministic: invalid path should not look like a summary"
        )


def test_run_case(case: dict) -> None:
    mode = eval_mode()
    try:
        result = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR, mode=mode)
    except AgentInvocationError as exc:
        import pytest

        pytest.skip(f"ADK not reachable: {exc}")
    except FileNotFoundError as exc:
        import pytest

        pytest.skip(str(exc))

    complaint_ref = case["input"]["complaint_ref"]
    raw = result.response.raw_output if isinstance(result.response.raw_output, dict) else {}
    _assert_deterministic(case, raw, complaint_ref)

    response = enrich(result.response, complaint_ref=complaint_ref)

    if judges_enabled():
        response = prepare_for_judges(case, response)
        judges = evaluate(AGENT, METRICS_SUITE, case, response)
        failed = [(j.name, j.score, j.reason) for j in judges.failed]
        assert not failed, failed
