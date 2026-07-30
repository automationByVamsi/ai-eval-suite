"""
Knowledge Agent — run generated goldens from testdata/knowledge_agent/golden.

Uses the same flow as sanity:
  run → deterministic → prepare_response → prepare_sample → optional judges

If no goldens have been generated yet, this module is skipped.
"""

from __future__ import annotations

import pytest

from src.core.exceptions import AgentInvocationError
from src.eval import prepare_sample
from src.parsers.knowledge_agent import prepare_response
from src.runners.case_runner import eval_mode, judges_enabled, run_case
from src.runners.evaluate import evaluate
from tests.knowledge_agent.conftest import AGENT, METRICS_SUITE
from tests.knowledge_agent.ka_eval import run_deterministic
from tests.support.sanity import OUTPUT_DIR, assert_all_passed, load_suite_cases, publish_case

DATA_SUITE = "golden"
CASES = load_suite_cases(
    AGENT,
    DATA_SUITE,
    required_input_keys=["question"],
    require_cases=False,
)
CASE_IDS = [c["test_case_id"] for c in CASES]

pytestmark = pytest.mark.skipif(
    not CASES,
    reason="No generated goldens under testdata/knowledge_agent/golden",
)


@pytest.fixture(params=CASES, ids=CASE_IDS)
def case(request: pytest.FixtureRequest) -> dict:
    return request.param


def test_run_case(case: dict) -> None:
    mode = eval_mode()
    try:
        result = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR, mode=mode)
    except AgentInvocationError as exc:
        pytest.skip(f"ADK not reachable: {exc}")
    except FileNotFoundError as exc:
        pytest.skip(str(exc))

    question = case["input"]["question"]
    raw = result.response.raw_output if isinstance(result.response.raw_output, dict) else {}
    det, fields = run_deterministic(case, raw, question)

    response = prepare_sample(case, prepare_response(case, result.response))
    judges: list = []
    if judges_enabled():
        judges = evaluate(AGENT, METRICS_SUITE, case, response, publish=False).judges

    publish_case(
        agent=AGENT,
        suite=METRICS_SUITE,
        case=case,
        response=response,
        deterministic=det,
        judges=judges,
        result_fields=fields,
    )

    assert_all_passed(det, label="deterministic")
    assert_all_passed(judges, label="judges")
