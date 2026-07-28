"""
Knowledge Agent — run + evaluate only.

Setup (cases / input checks) lives in conftest.py.

  EVAL_MODE=live|cache
  RUN_JUDGES=true   → also run CORTEX suite judges

  make test-ka-sanity
  make test-ka-sanity-judges
"""

from __future__ import annotations

from src.core.exceptions import AgentInvocationError
from src.parsers.knowledge_agent import enrich, extract
from src.runners.case_runner import eval_mode, judges_enabled, run_case
from src.runners.evaluate import evaluate
from tests.knowledge_agent.conftest import AGENT, METRICS_SUITE
from tests.support.sanity import DATA_SUITE, OUTPUT_DIR


def _assert_deterministic(case: dict, raw: dict, question: str) -> None:
    view = extract(raw)
    expected = case.get("expected") or {}

    assert view.answer.strip(), "deterministic: empty agent answer"
    assert view.rewritten_query.strip(), "deterministic: missing rewritten_query"
    assert view.anchor_page_id.strip(), "deterministic: missing anchor_page_id"
    assert question.strip(), "deterministic: case input.question required"

    for kw in expected.get("keywords") or []:
        assert str(kw).lower() in view.answer.lower(), (
            f"deterministic: keyword {kw!r} not found in answer"
        )

    want_anchor = expected.get("expected_anchor_page_id")
    if want_anchor:
        assert view.anchor_page_id == str(want_anchor), (
            f"deterministic: anchor_page_id={view.anchor_page_id!r}, expected {want_anchor!r}"
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

    question = case["input"]["question"]
    raw = result.response.raw_output if isinstance(result.response.raw_output, dict) else {}
    _assert_deterministic(case, raw, question)

    response = enrich(result.response, question=question)

    if judges_enabled():
        judges = evaluate(AGENT, METRICS_SUITE, case, response)
        failed = [(j.name, j.score, j.reason) for j in judges.failed]
        assert not failed, failed
