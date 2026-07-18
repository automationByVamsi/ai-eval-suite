"""
Field-by-field tests for Stage 1 (query rewrite) deterministic checks:
every value parse_stage1() extracts from a real captured trace, and every
DeterministicCheckResult run_deterministic() derives from it - including the
*reason* text on failure, not just pass/fail.

Complements tests/knowledge_agent/test_stage1.py (which only covers the
happy path plus "the rewrite never ran") by isolating each of the two checks
so a state-propagation failure can't hide behind a rewrite failure, or vice
versa.
"""

import copy
import json
from pathlib import Path

import pytest

from src.core.config import load_stage_config
from src.evaluators.knowledge_agent.stage1_query_rewrite import Stage1QueryRewriteEvaluator
from src.runners.factories import MetricFactory

SAMPLE_RAW_OUTPUT = json.loads(Path("sample-agent-response.json").read_text())
QUESTION = "How do I request VPN access for remote work?"


def _envelope(raw_output: dict) -> dict:
    """Wrap a raw ADK capture in the {test_case, raw_output} shape parse_stage1() expects."""
    return {
        "test_case": {
            "test_case_id": "TC_SAMPLE",
            "agent_name": "knowledge_agent_local",
            "input": {"question": QUESTION},
            "expected": {},
        },
        "raw_output": raw_output,
    }


@pytest.fixture
def evaluator():
    metric_factory = MetricFactory("configs/cortex.yaml")
    stage_config = load_stage_config("knowledge_agent", "stage1_query_rewrite")
    return Stage1QueryRewriteEvaluator(metric_factory, stage_config)


@pytest.fixture
def raw_trace():
    return _envelope(copy.deepcopy(SAMPLE_RAW_OUTPUT))


# ---- parse_stage1(): every field it fetches, checked individually ----


def test_question_comes_from_the_test_case_input(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.question == QUESTION


def test_rewrite_ran_is_true_when_query_rewrite_agent_event_exists(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.rewrite_ran is True


def test_rewritten_query_is_parsed_from_the_agents_json_text(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.rewritten_query == "VPN remote access request procedure"


def test_carried_into_state_matches_the_final_state_value(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.carried_into_state is True


def test_answer_is_the_agent_output_field(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.answer == SAMPLE_RAW_OUTPUT["agentOutput"]


def test_context_is_the_retrieved_context_list(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.context == SAMPLE_RAW_OUTPUT["context"]


def test_events_is_the_full_raw_events_list(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert len(parsed.events) == len(SAMPLE_RAW_OUTPUT["raw_events"])


def test_session_id_and_latency_pass_through_unchanged(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    assert parsed.session_id == SAMPLE_RAW_OUTPUT["sessionId"]
    assert parsed.latency_ms == SAMPLE_RAW_OUTPUT["latency_ms"]


# ---- run_deterministic(): every check it derives, pass AND fail cases ----


def test_both_checks_pass_on_the_real_trace(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    results = evaluator.run_deterministic(parsed)

    assert [r.name for r in results] == ["rewrite_step_ran", "rewritten_query_carried_into_state"]
    assert all(r.passed for r in results)
    assert all(r.reason == "" for r in results)


def test_rewrite_step_ran_fails_with_reason_when_event_missing(evaluator, raw_trace):
    broken = copy.deepcopy(raw_trace)
    broken["raw_output"]["raw_events"] = [
        e for e in broken["raw_output"]["raw_events"] if e.get("author") != "query_rewrite_agent"
    ]

    parsed = evaluator.parse_trace(broken)
    results = {r.name: r for r in evaluator.run_deterministic(parsed)}

    assert results["rewrite_step_ran"].passed is False
    assert results["rewrite_step_ran"].reason == "No query_rewrite event found in the trace"
    # rewritten_query is None when the rewrite never ran, so this check fails
    # too - it's a *consequence* of the missing rewrite, not tested as an
    # independent failure mode (see the next test for that).
    assert results["rewritten_query_carried_into_state"].passed is False


def test_carried_into_state_fails_independently_when_state_propagation_breaks(evaluator, raw_trace):
    """The rewrite ran and produced a query, but it never landed in session
    state - this must fail on its own, without rewrite_step_ran also failing."""
    broken = copy.deepcopy(raw_trace)
    for event in broken["raw_output"]["raw_events"]:
        event.get("actions", {}).get("stateDelta", {}).pop("rewritten_query", None)

    parsed = evaluator.parse_trace(broken)
    results = {r.name: r for r in evaluator.run_deterministic(parsed)}

    assert results["rewrite_step_ran"].passed is True
    assert results["rewritten_query_carried_into_state"].passed is False
    assert results["rewritten_query_carried_into_state"].reason == (
        "state.rewritten_query does not match the query_rewrite event output"
    )
