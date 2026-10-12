"""Knowledge Agent expected-error checks: a case passes when the agent refuses with the expected error."""

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
        run = run_suite("knowledge_agent", "negative", judges=False, case_ids=["KA_ERR_003"])
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
        run = run_suite("knowledge_agent", "negative", judges=False, case_ids=["KA_ERR_003"])
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
