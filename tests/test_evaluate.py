"""Unit tests for shared evaluate helper (judges path mocked offline where needed)."""

from pathlib import Path

import pytest

from src.models.agent_response import AgentResponse
from src.runners.evaluate import evaluate, load_trace
from src.verdict.ka_stages import prepare_stage1


def test_load_trace_wrapped_and_flat(tmp_path: Path):
    flat = tmp_path / "a.json"
    flat.write_text(
        '{"agentOutput": "ans", "raw_events": [], "sessionId": "1"}',
        encoding="utf-8",
    )
    w = load_trace(flat, {"test_case_id": "T", "input": {"question": "hi"}})
    assert w["raw_output"]["agentOutput"] == "ans"
    assert w["test_case"]["input"]["question"] == "hi"

    wrapped_path = tmp_path / "b.json"
    wrapped_path.write_text(
        '{"test_case": {"input": {"question": "old"}}, "raw_output": {"agentOutput": "x", "raw_events": []}}',
        encoding="utf-8",
    )
    w2 = load_trace(wrapped_path, {"input": {"question": "new"}, "expected": {}})
    assert w2["test_case"]["input"]["question"] == "new"


def test_ka_stage1_deterministic_via_ka_helper():
    trace = Path("outputs/traces/knowledge_agent/sanity/TC_001.json")
    if not trace.exists():
        pytest.skip("missing KA sanity trace")

    case = {
        "test_case_id": "TC_001",
        "input": {"question": "How do I support someone gambling?"},
        "expected": {},
    }
    _parsed, det, response = prepare_stage1(str(trace), case)
    assert isinstance(response, AgentResponse)
    failed = [c.name for c in det if not c.passed]
    assert not failed, failed


def test_evaluate_resolves_suite_without_running_cortex(monkeypatch):
    """evaluate uses suite→catalog; empty metric list means no CORTEX calls."""
    import src.runners.evaluate as ev

    monkeypatch.setattr(ev, "resolve_suite_metrics", lambda *a, **k: [])
    result = evaluate(
        "knowledge_agent",
        "stage1_query_rewrite",
        {"test_case_id": "T", "input": {"question": "q"}},
        AgentResponse(answer="a", metadata={"rewritten_query": "r"}),
        publish=False,
    )
    assert result.suite == "stage1_query_rewrite"
    assert result.judges == []
    assert result.passed
