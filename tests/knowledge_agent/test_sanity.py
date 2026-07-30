"""
Knowledge Agent — run + evaluate only.

Setup (cases / input checks) lives in conftest.py.

  EVAL_MODE=live|cache
  RUN_JUDGES=true   → also run suite judges

  DeepEval (default):
    make test-ka-sanity-judges

  Pegasus (same test file; data via prepare_response → prepare_sample):
    make test-ka-sanity-pegasus-judges
    METRIC_MODE=pegasus|pegasus_ragas|pegasus_deepeval
    Missing required fields → MetricContractError (fail loud)
"""

from __future__ import annotations

from src.core.exceptions import AgentInvocationError
from src.eval import prepare_sample
from src.parsers.knowledge_agent import prepare_response
from src.runners.case_runner import eval_mode, judges_enabled, run_case
from src.runners.evaluate import evaluate
from tests.knowledge_agent.conftest import AGENT, METRICS_SUITE
from tests.knowledge_agent.ka_eval import run_deterministic
from tests.support.sanity import DATA_SUITE, OUTPUT_DIR, assert_all_passed, publish_case


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
