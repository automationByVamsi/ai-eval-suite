"""Response alignment (Pegasus agentic ResponseAlignment) and what it needs: every answer shape read
from the trace, question_type sent to the agent, and the agentic column mapping."""

import copy
import json
import sys
import types

from conftest import ROOT

from src.core.agent_config import load_agent
from src.fields.extract import extract
from src.metrics import judges
from src.runners.suite_runner import _message, run_suite

WHAT = json.loads((ROOT / "tests/fixtures/ka_trace_what.json").read_text())   # a real `what` trace


def _with_answer(question_type, answer):
    """The `what` trace with its final output's answer replaced (how / yes_no shapes)."""
    trace = copy.deepcopy(WHAT)
    final = trace["raw_events"][-1]["output"]
    final["question_type"], final["answer"] = question_type, answer
    return trace


def _fields(trace):
    values, missing = extract(trace, load_agent("knowledge_agent").fields, offline=True, fetch=set())
    assert missing == []
    return values


# --- every answer shape is read (no more ERROR for how / what / yes_no) -------------------------

def test_what_answer_definitions():
    values = _fields(WHAT)
    assert values["question_type"] == "what"
    assert values["answer"].startswith("This is the required verification level for Personal Banking")
    assert values["cited_page_ids"] == ["40015"]
    assert values["agent_response"]["answer"]["definitions"][0]["phrase"] == "Minimum Standard Risk"


def test_how_answer_steps():
    values = _fields(_with_answer("how", {"steps": [
        {"description": "Open Colleague Tools in MCP.", "page_id": "40345"},
        {"description": "Gain consent if on the phone.", "page_id": "40015"}]}))
    assert values["answer"] == "Open Colleague Tools in MCP.\nGain consent if on the phone."
    assert values["cited_page_ids"] == ["40345", "40015"]


def test_yes_no_answer():
    values = _fields(_with_answer("yes_no", {"answer": "yes", "explanation": "A third party can tell us.",
                                             "page_ids": ["40022"]}))
    assert values["answer"] == "A third party can tell us."
    assert values["yes_no_verdict"] == "yes" and values["cited_page_ids"] == ["40022"]


# --- question_type is sent to the agent ----------------------------------------------------------

def test_question_type_is_sent_as_json_and_plain_questions_stay_plain():
    agent = load_agent("knowledge_agent")
    typed = {"input": {"question": "How do I add a support need?", "question_type": "how"}}
    assert json.loads(_message(agent, typed)) == {"query": "How do I add a support need?", "question_type": "how"}
    plain = {"input": {"question": "How do I add a support need?"}}
    assert _message(agent, plain) == "How do I add a support need?"            # unchanged for old cases


# --- the Pegasus call: agentic module, its own columns, no method= ------------------------------

def _fake_pegasus(monkeypatch, calls):
    class Judge:
        def __init__(self, **kwargs):
            calls.append({"class": type(self).__name__, "kwargs": kwargs})

        def evaluate(self, frame):
            calls[-1]["row"] = frame.to_dict("records")[0]
            if type(self).__name__ == "ResponseAlignment":       # agentic: the reason is per sample
                return {"score": 0.9, "passed": True, "individual_scores": [0.9], "individual_results": [{
                    "score": 0.9, "raw_score": 9.1,
                    "explanation": "The answer gives definitions, as a what question needs."}]}
            return {"score": [0.9], "reasoning": ["The answer gives definitions, as a what question needs."]}

    agentic = types.ModuleType("pegasus.metrics.agentic")
    agentic.ResponseAlignment = type("ResponseAlignment", (Judge,), {})
    rag = types.ModuleType("pegasus.metrics.rag")
    rag.AnswerRelevancy = type("AnswerRelevancy", (Judge,), {})
    package = types.ModuleType("pegasus")
    metrics = types.ModuleType("pegasus.metrics")
    metrics.agentic, metrics.rag = agentic, rag
    for name, module in {"pegasus": package, "pegasus.metrics": metrics, "pegasus.metrics.agentic": agentic,
                         "pegasus.metrics.rag": rag}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    monkeypatch.setattr(judges, "pegasus_has_credentials", lambda: True)
    monkeypatch.setattr(judges.cortex_client, "pegasus_llm", lambda: "LLM")


def test_response_alignment_run_on_a_saved_what_trace(outputs, monkeypatch):
    calls = []
    _fake_pegasus(monkeypatch, calls)
    folder = outputs / "outputs/traces/knowledge_agent/response_alignment_only"
    folder.mkdir(parents=True)
    (folder / "TC_QT_WHAT.json").write_text(json.dumps(WHAT))

    case = run_suite("knowledge_agent", "response_alignment_only", offline=True, case_ids=["TC_QT_WHAT"]).cases[0]
    [result] = case.results
    assert (result.name, result.status, result.score, result.engine) == ("response_alignment", "pass", 0.9, "pegasus")
    assert result.reason == "The answer gives definitions, as a what question needs. (raw score 9.1/10)"

    [call] = calls
    assert call["class"] == "ResponseAlignment"
    assert call["kwargs"] == {"llm": "LLM"}                        # ResponseAlignment takes no method=
    row = call["row"]
    assert set(row) == {"query", "agent_response", "background"}   # its own column names
    assert row["query"] == "What level of verification is required when adding a support need?"
    sent = json.loads(row["agent_response"])                       # the whole final output, as JSON text
    assert sent["question_type"] == "what" and sent["answer"]["definitions"]
    assert "what = definitions" in row["background"]


def test_rag_metrics_still_get_method_and_their_columns(outputs, monkeypatch):
    calls = []
    _fake_pegasus(monkeypatch, calls)
    traces = outputs / "outputs/traces/knowledge_agent"
    (traces / "relevance_only").mkdir(exist_ok=True)
    (traces / "relevance_only" / "TC_002.json").write_text((traces / "sanity" / "TC_002.json").read_text())
    case = run_suite("knowledge_agent", "relevance_only", offline=True, case_ids=["TC_002"]).cases[0]
    assert case.results[0].status == "pass"
    [call] = calls
    assert call["kwargs"] == {"llm": "LLM", "method": "pegasus"}
    assert set(call["row"]) == {"question", "answer", "retrieved_contexts"}


def test_new_trace_shape_answer_envelope_and_business_area():
    """Final output wrapped as {response_type, answer: {...}}: the same fields still extract."""
    values = _fields(json.loads((ROOT / "tests/fixtures/ka_trace_v2_general.json").read_text()))
    assert values["question_type"] == "general" and values["confidence"] == "HIGH"
    assert values["answer"].startswith("To support a customer experiencing financial harm")
    assert values["cited_page_ids"] == ["32177"] and values["evidence_page_ids"] == ["32177"]
    assert values["agent_response"]["response_type"] == "answer"
    agent = load_agent("knowledge_agent")
    sent = json.loads(_message(agent, {"input": {"question": "q?", "business_area": "Business Banking"}}))
    assert sent == {"query": "q?", "business_area": "Business Banking"}           # question_type optional
