"""
Layer 1 (deterministic) checks for stage 1 don't need CORTEX or the network -
these tests exercise only parse_trace() + run_deterministic() directly,
against the sample trace committed at outputs/traces/knowledge_agent/sanity/TC_001.json.
"""

import copy
import json
from pathlib import Path

import pytest

from src.core.config import load_stage_config
from src.evaluators.knowledge_agent.stage1_query_rewrite import Stage1QueryRewriteEvaluator
from src.runners.factories import MetricFactory

TRACE_PATH = Path("outputs/traces/knowledge_agent/sanity/TC_001.json")


@pytest.fixture
def evaluator():
    metric_factory = MetricFactory("configs/cortex.yaml")
    stage_config = load_stage_config("knowledge_agent", "stage1_query_rewrite")
    return Stage1QueryRewriteEvaluator(metric_factory, stage_config)


@pytest.fixture
def raw_trace():
    return json.loads(TRACE_PATH.read_text())


def test_rewrite_step_ran_and_carried_into_state(evaluator, raw_trace):
    parsed = evaluator.parse_trace(raw_trace)
    results = evaluator.run_deterministic(parsed)
    assert all(r.passed for r in results), [r.reason for r in results if not r.passed]


def test_fails_when_rewrite_event_is_missing(evaluator, raw_trace):
    broken = copy.deepcopy(raw_trace)
    broken["raw_output"]["raw_events"] = [
        e for e in broken["raw_output"]["raw_events"] if e.get("author") != "query_rewrite_agent"
    ]

    parsed = evaluator.parse_trace(broken)
    results = evaluator.run_deterministic(parsed)

    assert not all(r.passed for r in results)
    failed_names = {r.name for r in results if not r.passed}
    assert "rewrite_step_ran" in failed_names
