"""
Tests for the framework itself. They never call a real agent or a real judge:
runs replay the traces in outputs/traces/, and judges talk to a fake CORTEX gateway.

    make test
"""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from evalkit import config, judges, new_agent, results, runner, verdict
from evalkit.config import ROOT, ConfigError, load_agent
from evalkit.results import load_run


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Run everything in a temp outputs/ + baselines/, seeded with the committed traces."""
    shutil.copytree(ROOT / "outputs" / "traces", tmp_path / "outputs" / "traces")
    monkeypatch.setattr(results, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(runner, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(verdict, "BASELINES_DIR", tmp_path / "baselines")
    return tmp_path


@pytest.fixture
def fake_cortex(monkeypatch):
    """A local stand-in for the CORTEX gateway that answers every judge prompt favourably."""
    reply = {"statements": ["s"], "verdicts": [{"verdict": "yes", "reason": "ok"}], "truths": ["t"],
             "claims": ["c"], "steps": ["check the answer"], "score": 9, "reason": "looks right"}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("CORTEX_HOST", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("CORTEX_CLIENT_ID", "test")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    from evalkit import cortex
    cortex.deepeval_llm.cache_clear()
    yield
    server.shutdown()


# --- config ---------------------------------------------------------------------------------

def test_every_agent_config_loads():
    for name in ("knowledge_agent", "fact_find_workflow"):
        agent = load_agent(name)
        assert agent.suites, name


def test_typo_in_metric_is_caught_at_load(tmp_path, monkeypatch):
    folder = tmp_path / "agents" / "demo"
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\n"
        "metrics: {relevance: {treshold: 0.7}}\n"
        "suites: {sanity: {metrics: [relevance]}}\n"
    )
    from evalkit import config
    monkeypatch.setattr(config, "AGENTS_DIR", tmp_path / "agents")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_agent("demo")


# --- runner ---------------------------------------------------------------------------------

def test_offline_run_passes_deterministic_checks(outputs):
    run = runner.run_suite("fact_find_workflow", "sanity", offline=True, judges=False)
    assert run.passed
    names = {r.name for c in run.cases for r in c.results}
    assert {"fact:party_id", "fact:postcode", "invalid_complaint_signal"} <= names


def test_missing_trace_is_an_error_not_a_skip(outputs):
    run = runner.run_suite("knowledge_agent", "sanity", offline=True, judges=False)
    by_id = {c.case_id: c for c in run.cases}
    assert by_id["TC_012"].status == results.ERROR
    assert not run.passed


def test_run_is_saved_and_reloaded(outputs):
    run = runner.run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=["TC_001"])
    again = load_run("latest", "knowledge_agent", "sanity")
    assert again.run_id == run.run_id
    assert again.cases[0].results[0].name == "answer_non_empty"


def test_live_run_calls_adk_and_saves_the_trace(outputs, monkeypatch):
    events = [
        {"author": "search_engine_workflow", "actions": {"stateDelta": {
            "rewritten_query": "How to request VPN access", "anchor_page_id": "8194"}}},
        {"author": "answer_agent", "content": {"role": "model", "parts": [{"text": "Raise a VPN ticket."}]}},
    ]
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(self.path)
            reply = {"id": "session-1"} if self.path.endswith("/sessions") else events
            if self.path == "/run":
                assert body["new_message"]["parts"][0]["text"] == "How do I request VPN access for remote work?"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("KNOWLEDGE_ADK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("KNOWLEDGE_ADK_BASE_PATH", "")
    monkeypatch.setenv("KNOWLEDGE_ADK_APP_NAME", "knowledge_agent")
    monkeypatch.setenv("KNOWLEDGE_ADK_USER_ID", "eval_user")
    try:
        run = runner.run_suite("knowledge_agent", "sanity", judges=False, case_ids=["TC_002"])
    finally:
        server.shutdown()

    case = run.cases[0]
    assert case.status == results.PASS, case.results
    assert case.answer == "Raise a VPN ticket."
    assert seen == ["/apps/knowledge_agent/users/eval_user/sessions", "/run"]
    assert json.loads(Path(case.trace).read_text())["sessionId"] == "session-1"
    assert (run.folder / "traces" / "TC_002__rep1.json").is_file()


def test_non_adk_agent_uses_its_client_py(tmp_path, monkeypatch, outputs):
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "_template", agents / "_template")
    for module in (config, new_agent):
        monkeypatch.setattr(module, "AGENTS_DIR", agents)
    monkeypatch.setattr(new_agent, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("")
    new_agent.create_agent("rest_agent")
    (agents / "rest_agent" / "client.py").write_text(
        "def call_agent(settings, message):\n"
        "    return {'agentOutput': 'VPN: raise a ticket about ' + message}\n")

    run = runner.run_suite("rest_agent", "sanity", judges=False)
    assert run.passed
    assert run.cases[0].answer.startswith("VPN: raise a ticket")


# --- judges ---------------------------------------------------------------------------------

def test_judge_skips_when_the_case_lacks_the_data():
    result = judges.run_judge("correctness", {}, {"question": "q", "answer": "a", "expected_answer": ""})
    assert result.status == results.SKIP
    assert "expected_answer" in result.reason


def test_judge_field_can_point_at_a_parser_field(monkeypatch):
    seen = {}

    def fake_score(name, metric, values, threshold):
        seen.update(values)
        return 0.9, "fine"

    monkeypatch.setattr(judges, "_score_deepeval", fake_score)
    spec = {"rubric": str(ROOT / "agents/knowledge_agent/rubrics/intent_preservation.md"),
            "answer": "rewritten_query"}
    result = judges.run_judge("intent", spec, {"question": "q", "answer": "final", "rewritten_query": "rq"})
    assert result.status == results.PASS and seen["answer"] == "rq"


def test_judge_crash_is_an_error_not_a_low_score(monkeypatch):
    def boom(*args):
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(judges, "_score_deepeval", boom)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    result = judges.run_judge("relevance", {}, {"question": "q", "answer": "a"})
    assert result.status == results.ERROR and result.score is None


def test_engine_rule(monkeypatch):
    rubric = str(ROOT / "agents/knowledge_agent/rubrics/intent_preservation.md")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    assert judges.pick_engine(judges.definition("relevance", {})) == "pegasus"
    assert judges.pick_engine(judges.definition("summarization", {})) == "deepeval"   # not in Pegasus
    assert judges.pick_engine(judges.definition("mine", {"rubric": rubric})) == "deepeval"
    assert judges.pick_engine(judges.definition("relevance", {"engine": "deepeval"})) == "deepeval"
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    assert judges.pick_engine(judges.definition("relevance", {})) == "deepeval"       # fallback


def test_metric_library_is_valid():
    assert {"relevance", "faithfulness", "correctness"} <= set(judges.library())


def test_new_agent_is_ready_to_run(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "_template", agents / "_template")
    (tmp_path / ".env.example").write_text("")
    for module in (config, new_agent):
        monkeypatch.setattr(module, "AGENTS_DIR", agents)
    monkeypatch.setattr(new_agent, "ROOT", tmp_path)

    new_agent.create_agent("claims_agent", input_field="claim_id")
    agent = load_agent("claims_agent")
    assert agent.input_field == "claim_id"
    assert "CLAIMS_AGENT_BASE_URL" in (agents / "claims_agent" / "agent.yaml").read_text()
    assert "CLAIMS_AGENT_BASE_URL=" in (tmp_path / ".env.example").read_text()
    assert runner.load_cases(agent, agent.suite("sanity"))[0]["input"] == {"claim_id": "How do I request VPN access?"}
    assert not (agents / "claims_agent" / "client.py").exists()     # ADK unless you opt in


def test_deepeval_judges_run_through_cortex(fake_cortex):
    fields = {"question": "How do I get VPN?", "answer": "Raise a ticket.", "contexts": ["Raise a ticket."],
              "expected_answer": "Raise a ticket."}
    for name in ("relevance", "faithfulness", "correctness"):
        result = judges.run_judge(name, {}, fields)
        assert result.status == results.PASS, (name, result.reason)
        assert result.engine == "deepeval"
    rubric = str(ROOT / "agents/knowledge_agent/rubrics/intent_preservation.md")
    assert judges.run_judge("intent", {"rubric": rubric}, fields).status == results.PASS


# --- verdict --------------------------------------------------------------------------------

def test_verdict_passes_against_itself_and_catches_a_regression(outputs):
    stable = runner.run_suite("fact_find_workflow", "sanity", offline=True, judges=False, build="1.0")
    verdict.save_baseline(stable)

    passed, rows, _ = verdict.compare(stable)
    assert passed and all(r["status"] == "ok" for r in rows)

    broken = load_run(stable.run_id)
    broken.cases[0].results[0].status = results.FAIL      # answer_non_empty now fails
    passed, rows, _ = verdict.compare(broken)
    assert not passed
    assert [r["result"] for r in rows if r["status"] == "regression"] == ["TC_001 :: check:answer_non_empty"]


def test_score_drop_is_a_regression_even_above_threshold(outputs):
    run = runner.run_suite("fact_find_workflow", "sanity", offline=True, judges=False)
    judge = results.Result("faithfulness", "judge", results.PASS, score=0.95, threshold=0.7, engine="pegasus")
    run.cases[0].results.append(judge)
    verdict.save_baseline(run)
    judge.score = 0.80                                     # still passes, but dropped 0.15
    passed, rows, _ = verdict.compare(run)
    assert not passed
    assert any(r["status"] == "regression" and "faithfulness" in r["result"] for r in rows)


def test_no_baseline_from_a_broken_run(outputs):
    run = runner.run_suite("knowledge_agent", "sanity", offline=True, judges=False)   # TC_012 errors
    with pytest.raises(ValueError, match="errors"):
        verdict.save_baseline(run)


def test_committed_traces_exist_for_offline_demo():
    assert list(Path(ROOT / "outputs" / "traces").glob("*/sanity/*.json"))


# --- synthesizer ----------------------------------------------------------------------------

def test_athena_page_cleans_to_the_committed_source():
    import importlib.util
    path = ROOT / "agents/knowledge_agent/synth/sources.py"
    spec = importlib.util.spec_from_file_location("ka_sources", path)
    sources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sources)

    page = json.loads((ROOT / "tests/fixtures/athena_page_8708.json").read_text())
    title, text = sources.page_to_text(page)
    committed = (ROOT / "agents/knowledge_agent/synth/sources/8708.txt").read_text().strip()
    assert f"{title}\n\n{text}".strip() == committed


def test_goldens_are_written_as_runnable_cases(tmp_path, monkeypatch):
    import deepeval.synthesizer
    from deepeval.dataset import Golden

    from evalkit import cortex, synth

    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "knowledge_agent", agents / "knowledge_agent")
    monkeypatch.setattr(config, "AGENTS_DIR", agents)
    from deepeval.models import DeepEvalBaseLLM

    class FakeLLM(DeepEvalBaseLLM):
        def load_model(self):
            return self

        def generate(self, prompt, schema=None):
            return ""

        async def a_generate(self, prompt, schema=None):
            return ""

        def get_model_name(self):
            return "fake"

    monkeypatch.setattr(cortex, "deepeval_llm", FakeLLM)
    styles_seen = []

    class FakeSynthesizer:
        def __init__(self, styling_config, **kwargs):
            styles_seen.append(styling_config)

        def generate_goldens_from_contexts(self, contexts, source_files, max_goldens_per_context, **kwargs):
            assert source_files == ["8708"]
            return [Golden(input=f"Question {i}?", expected_output="Answer.", source_file=source_files[0])
                    for i in range(max_goldens_per_context)]

    monkeypatch.setattr(deepeval.synthesizer, "Synthesizer", FakeSynthesizer)

    written = synth.generate_goldens("knowledge_agent")
    assert len(written) == 4                                         # 2 styles x 2 per source
    assert "advisor" in styles_seen[0].scenario.lower()             # instructions.md folded in
    agent = load_agent("knowledge_agent")
    cases = runner.load_cases(agent, agent.suite("golden"))
    assert cases[0]["input"] == {"question": "Question 0?"}
    assert cases[0]["expected"]["expected_answer"] == "Answer."
    assert cases[0]["expected"]["source"] == "8708"

    with pytest.raises(ConfigError, match="REPLACE=1"):             # never overwrite reviewed cases silently
        synth.generate_goldens("knowledge_agent")
    assert len(synth.generate_goldens("knowledge_agent", replace=True)) == 4
