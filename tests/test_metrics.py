"""LLM judges: engine choice, skip / error handling, and DeepEval through a fake CORTEX gateway."""

from conftest import ROOT

from src.core import results
from src.metrics import judges
from src.metrics.library import definition, library

RUBRIC = str(ROOT / "agents/knowledge_agent/rubrics/intent_preservation.md")


def test_metric_library_is_valid():
    assert {"relevance", "faithfulness", "correctness"} <= set(library())


def test_judge_skips_when_the_case_lacks_the_data():
    result = judges.run_judge("correctness", {}, {"question": "q", "answer": "a", "expected_answer": ""})
    assert result.status == results.SKIP
    assert "expected_answer" in result.reason


def test_judge_field_can_point_at_a_parser_field(monkeypatch):
    seen = {}

    def fake_score(name, metric, values, threshold):
        seen.update(values)
        return 0.9, "fine"

    monkeypatch.setattr(judges, "score_with_deepeval", fake_score)
    spec = {"rubric": RUBRIC, "answer": "rewritten_query"}
    result = judges.run_judge("intent", spec, {"question": "q", "answer": "final", "rewritten_query": "rq"})
    assert result.status == results.PASS and seen["answer"] == "rq"


def test_judge_crash_is_an_error_not_a_low_score(monkeypatch):
    def boom(*args):
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(judges, "score_with_deepeval", boom)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    result = judges.run_judge("relevance", {}, {"question": "q", "answer": "a"})
    assert result.status == results.ERROR and result.score is None


def test_engine_rule(monkeypatch):
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    assert judges.pick_engine(definition("relevance", {})) == "pegasus"
    assert judges.pick_engine(definition("summarization", {})) == "deepeval"     # not in Pegasus
    assert judges.pick_engine(definition("mine", {"rubric": RUBRIC})) == "deepeval"
    assert judges.pick_engine(definition("relevance", {"engine": "deepeval"})) == "deepeval"
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    assert judges.pick_engine(definition("relevance", {})) == "deepeval"         # fallback


def test_deepeval_judges_run_through_cortex(fake_cortex):
    fields = {"question": "How do I get VPN?", "answer": "Raise a ticket.", "contexts": ["Raise a ticket."],
              "expected_answer": "Raise a ticket."}
    for name in ("relevance", "faithfulness", "correctness"):
        result = judges.run_judge(name, {}, fields)
        assert result.status == results.PASS, (name, result.reason)
        assert result.engine == "deepeval"
    assert judges.run_judge("intent", {"rubric": RUBRIC}, fields).status == results.PASS

    last = fake_cortex[-1]
    assert last["x-lbg-origin-client-id"] == "test"
    assert last["authorization"] == "Bearer key-123"     # CorteX 2.0 API key
