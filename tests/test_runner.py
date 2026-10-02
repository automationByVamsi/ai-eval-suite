"""The evaluation loop: config loading, offline and live runs, test case loading, new agents, the CLI."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest
from conftest import ROOT, serve

from src import cli
from src.core import results
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.core.results import load_run
from src.onboarding.new_agent import create_agent
from src.runners.suite_runner import run_suite
from src.runners.test_cases import load_cases

# --- config ---------------------------------------------------------------------------------

# The Knowledge Agent sanity cases, with real traces committed in outputs/traces/ (29 Sep 2026 format).
# TC_002 takes the full metadata path; TC_012 falls back silently (no KB metadata, nothing disclosed).
WITH_TRACES = ["TC_002", "TC_012"]


def test_every_agent_config_loads():
    assert load_agent("knowledge_agent").suites


def test_typo_in_metric_is_caught_at_load(temp_agents):
    folder = temp_agents / "demo"
    folder.mkdir()
    (folder / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\n"
        "metrics: {relevance: {treshold: 0.7}}\n"
        "suites: {sanity: {metrics: [relevance]}}\n"
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_agent("demo")


# --- runs -----------------------------------------------------------------------------------

def test_offline_run_uses_fields_yaml_and_yaml_checks(outputs):
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=WITH_TRACES)
    by_id = {c.case_id: c for c in run.cases}
    good, degraded = by_id["TC_002"], by_id["TC_012"]
    assert good.status == results.PASS, [r for r in good.results if r.status != "pass"]
    assert good.answer.startswith("To add a Support Need in Multi-Channel Processes")   # answer.summary, not JSON
    names = {r.name for r in good.results}
    assert {"answer_non_empty", "branch_per_sub_query", "citations_in_evidence_set", "anchor_hit"} <= names
    failed = [r.name for r in degraded.results if r.status == results.FAIL]
    assert failed == ["fallback_disclosed"]                       # the silent fallback is caught
    assert not run.passed


def test_missing_trace_is_an_error_not_a_skip(outputs):
    (outputs / "outputs/traces/knowledge_agent/sanity/TC_012.json").unlink()
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False)
    by_id = {c.case_id: c for c in run.cases}
    assert by_id["TC_012"].status == results.ERROR
    assert not run.passed


def test_changed_trace_format_is_an_error_that_says_so(outputs):
    trace_file = outputs / "outputs/traces/knowledge_agent/sanity/TC_002.json"
    trace = json.loads(trace_file.read_text())
    trace["raw_events"][-1]["output"]["answer"] = {"text": "renamed"}      # answer.summary is gone
    trace_file.write_text(json.dumps(trace))
    case = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=["TC_002"]).cases[0]
    assert case.status == results.ERROR
    assert "['answer'] not found" in case.error and "make fields" in case.error


def test_run_is_saved_and_reloaded(outputs):
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=["TC_002"])
    again = load_run("latest", "knowledge_agent", "sanity")
    assert again.run_id == run.run_id
    assert again.cases[0].results[0].name == "answer_non_empty"
    assert again.cases[0].results[0].group == "basic"
    assert again.cases[0].details["evidence_titles"][0] == "How To Add a Support Need in MCP"   # for the dashboard
    assert again.cases[0].input == {"question": "How do I add a support need?"}
    assert again.metrics == [] and again.checks is None


def test_live_run_calls_adk_and_saves_the_trace(outputs, monkeypatch):
    # The fake agent replies with the events of the real TC_002 trace.
    events = json.loads((ROOT / "outputs/traces/knowledge_agent/sanity/TC_002.json").read_text())["raw_events"]
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(self.path)
            reply = {"id": "session-1"} if self.path.endswith("/sessions") else events
            if self.path == "/run":
                assert body["new_message"]["parts"][0]["text"] == "How do I add a support need?"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    server, url = serve(Handler)
    monkeypatch.setenv("KNOWLEDGE_ADK_BASE_URL", url)
    monkeypatch.setenv("KNOWLEDGE_ADK_BASE_PATH", "")
    monkeypatch.setenv("KNOWLEDGE_ADK_APP_NAME", "knowledge_agent")
    monkeypatch.setenv("KNOWLEDGE_ADK_USER_ID", "eval_user")
    try:
        run = run_suite("knowledge_agent", "sanity", judges=False, case_ids=["TC_002"])
    finally:
        server.shutdown()

    case = run.cases[0]
    assert case.status == results.PASS, case.results
    assert case.answer.startswith("To add a Support Need in Multi-Channel Processes")
    assert seen == ["/apps/knowledge_agent/users/eval_user/sessions", "/run"]
    assert json.loads(Path(case.trace).read_text())["sessionId"] == "session-1"
    assert (run.folder / "traces" / "TC_002__rep1.json").is_file()


def test_non_adk_agent_uses_its_client_py(temp_agents, outputs):
    create_agent("rest_agent")
    (temp_agents / "rest_agent" / "client.py").write_text(
        "def call_agent(settings, message):\n"
        "    return {'agentOutput': 'VPN: raise a ticket about ' + message}\n")
    run = run_suite("rest_agent", "sanity", judges=False)
    assert run.passed
    assert run.cases[0].answer.startswith("VPN: raise a ticket")


def test_committed_traces_exist_for_offline_demo():
    assert list(Path(ROOT / "outputs" / "traces").glob("*/sanity/*.json"))


# --- onboarding -----------------------------------------------------------------------------

def test_new_agent_is_ready_to_run(temp_agents):
    create_agent("claims_agent", input_field="claim_id")
    agent = load_agent("claims_agent")
    assert agent.input_field == "claim_id"
    assert "CLAIMS_AGENT_BASE_URL" in (temp_agents / "claims_agent" / "agent.yaml").read_text()
    assert "CLAIMS_AGENT_BASE_URL=" in (temp_agents.parent / "env" / ".env.example").read_text()
    assert load_cases(agent, agent.suite("sanity"))[0]["input"] == {"claim_id": "How do I request VPN access?"}
    assert not (temp_agents / "claims_agent" / "client.py").exists()     # ADK unless you opt in


# --- env files ------------------------------------------------------------------------------

def test_agent_env_file_overrides_shared_but_not_shell(temp_agents, monkeypatch):
    import os

    from src.core import env
    env_dir = temp_agents.parent / "env"
    (env_dir / ".env").write_text("A=shared\nB=shared\nC=shared\n")
    (env_dir / ".env.claims_agent").write_text("B=agent\nC=agent\n")
    for key in ("A", "B", "C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("C", "shell")
    monkeypatch.setattr(env, "_SHELL_VARS", {"C"})

    env.load_shared_env()
    create_agent("claims_agent")
    load_agent("claims_agent")            # loads env/.env.claims_agent
    assert (os.environ["A"], os.environ["B"], os.environ["C"]) == ("shared", "agent", "shell")


# --- command line ---------------------------------------------------------------------------

def test_cli_runs_and_reports_config_errors_in_one_line(outputs, capsys, monkeypatch):
    only_traced = [arg for case in WITH_TRACES for arg in ("--case", case)]
    assert cli.main(["run", "knowledge_agent", "sanity", "--offline", "--no-judges", "--case", "TC_002"]) == 0
    assert "1 passed" in capsys.readouterr().out
    assert cli.main(["run", "knowledge_agent", "sanity", "--offline", "--no-judges", *only_traced]) == 1
    monkeypatch.setattr("sys.argv", ["src", "run", "no_such_agent", "sanity"])
    assert cli.run_cli() == 1
    assert capsys.readouterr().err.startswith("ERROR: No agent 'no_such_agent'")


def test_comment_after_an_empty_env_value_is_not_the_value(tmp_path, monkeypatch):
    import os

    from src.core import env
    (tmp_path / ".env").write_text("CORTEX_BASE_URL=        # optional; defaults to CORTEX_HOST\nX_KEEP=v  # x\n")
    monkeypatch.delenv("CORTEX_BASE_URL", raising=False)
    monkeypatch.delenv("X_KEEP", raising=False)
    monkeypatch.setattr(env, "_SHELL_VARS", set())
    env.load_env_file(tmp_path / ".env")
    assert os.environ["CORTEX_BASE_URL"] == "" and os.environ["X_KEEP"] == "v"
