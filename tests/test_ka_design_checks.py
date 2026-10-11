"""Checks from the Knowledge Agent I/O design: expected errors (the agent refuses), the PII guardrail on the
search queries, valid relation labels and in-scope business areas."""

import json

from conftest import ROOT, serve

from src.core import results
from src.core.agent_config import load_agent
from src.fields import checks
from src.runners.suite_runner import run_suite

TC_002 = json.loads((ROOT / "outputs/traces/knowledge_agent/sanity/TC_002.json").read_text())


def _fake_agent(monkeypatch, handler_reply):
    """A fake ADK agent: /sessions gives a session id, /run replies with handler_reply() -> (status, body)."""
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            status, body = (200, {"id": "s1"}) if self.path.endswith("/sessions") else handler_reply()
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server, url = serve(Handler)
    for name, value in {"BASE_URL": url, "BASE_PATH": "", "APP_NAME": "knowledge_agent", "USER_ID": "u"}.items():
        monkeypatch.setenv(f"KNOWLEDGE_ADK_{name}", value)
    monkeypatch.setenv("KNOWLEDGE_ADK_RETRIES", "0")
    return server


def test_an_expected_error_is_the_agent_s_answer(outputs, monkeypatch):
    # KA_ERR_003: a query that matches nothing -> the agent refuses with InsufficientContextError (HTTP 500).
    refusal = {"detail": "InsufficientContextError: We were unable to identify a relevant starting page for "
                         "your query. Please rephrase your query and try again."}
    server = _fake_agent(monkeypatch, lambda: (500, refusal))
    try:
        run = run_suite("knowledge_agent", "errors", judges=False, case_ids=["KA_ERR_003"])
    finally:
        server.shutdown()
    case = run.cases[0]
    assert case.status == results.PASS, (case.error, case.results)
    assert {r.name: r.status for r in case.results}["returned_expected_error"] == results.PASS
    assert "InsufficientContextError" in case.details["agent_error"]


def test_an_answer_where_an_error_was_expected_fails(outputs, monkeypatch):
    # The agent invents an answer to an unanswerable question instead of refusing.
    server = _fake_agent(monkeypatch, lambda: (200, TC_002["raw_events"]))
    try:
        run = run_suite("knowledge_agent", "errors", judges=False, case_ids=["KA_ERR_003"])
    finally:
        server.shutdown()
    case = run.cases[0]
    assert case.status == results.FAIL
    [refused] = [r for r in case.results if r.name == "returned_expected_error"]
    assert refused.status == results.FAIL and "agent_error has none of" in refused.reason


def test_the_wrong_error_type_fails():
    spec = load_agent("knowledge_agent").checks["returned_expected_error"]
    [result] = checks.run_checks({"r": spec}, {"agent_error": "HTTP 500 AthenaRetrievalError: search failed"},
                                 {"expected": {"expected_error": ["InsufficientContextError"]}})
    assert result.status == results.FAIL


def test_pii_must_not_reach_the_search_queries():
    spec = load_agent("knowledge_agent").checks["pii_not_sent_to_search"]
    privacy_case = {"expected": {"contains_pii": True}}
    leaked = {"rewritten_query": "add support need for mrs jane sample account 12345678",
              "branch_sub_queries": ["support need large print 30-99-50"]}
    [result] = checks.run_checks({"p": spec}, leaked, privacy_case)
    assert result.status == results.FAIL and "12345678" in result.reason and "30-99-50" in result.reason
    clean = {"rewritten_query": "add support need large print letters", "branch_sub_queries": ["large print"]}
    assert checks.run_checks({"p": spec}, clean, privacy_case)[0].status == results.PASS
    assert checks.run_checks({"p": spec}, leaked, {"expected": {}})[0].status == results.SKIP   # not a privacy case


def test_relation_labels_and_business_area_come_from_the_design():
    agent = load_agent("knowledge_agent")
    labels = {"l": agent.checks["relation_labels_valid"]}
    assert checks.run_checks(labels, {"expansion_labels": ["reference", "exception_to"]}, {})[0].status == results.PASS
    assert checks.run_checks(labels, {"expansion_labels": ["related_to"]}, {})[0].status == results.FAIL
    area = {"b": agent.checks["business_area_in_scope"]}
    assert checks.run_checks(area, {"input_business_area": "Customer Self-Service Online and App"}, {})[0].status \
        == results.PASS
    assert checks.run_checks(area, {"input_business_area": "CVH"}, {})[0].status == results.FAIL   # a code, not a name
    assert checks.run_checks(area, {}, {})[0].status == results.SKIP                                 # none sent
