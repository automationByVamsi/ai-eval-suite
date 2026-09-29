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

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(dict(self.headers))
            if len(seen) == 1:                     # first call: gateway busy -> the client must retry
                self.send_response(503)
                self.end_headers()
                return
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
    monkeypatch.setenv("CORTEX_API_KEY", "key-123")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    from evalkit import cortex
    cortex.deepeval_llm.cache_clear()
    yield seen
    server.shutdown()
    cortex.deepeval_llm.cache_clear()


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
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / ".env.example").write_text("")
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
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / ".env.example").write_text("")
    for module in (config, new_agent):
        monkeypatch.setattr(module, "AGENTS_DIR", agents)
    monkeypatch.setattr(new_agent, "ROOT", tmp_path)

    new_agent.create_agent("claims_agent", input_field="claim_id")
    agent = load_agent("claims_agent")
    assert agent.input_field == "claim_id"
    assert "CLAIMS_AGENT_BASE_URL" in (agents / "claims_agent" / "agent.yaml").read_text()
    assert "CLAIMS_AGENT_BASE_URL=" in (tmp_path / "env" / ".env.example").read_text()
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
    headers = {k.lower(): v for k, v in fake_cortex[-1].items()}
    assert headers["x-lbg-origin-client-id"] == "test"
    assert headers["authorization"] == "Bearer key-123"          # CorteX 2.0 API key


def test_env_files_agent_file_overrides_shared_but_not_shell(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("A=shared\nB=shared\nC=shared\n")
    (tmp_path / ".env.demo").write_text("B=agent\nC=agent\n")
    for key in ("A", "B", "C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("C", "shell")
    monkeypatch.setattr(config, "_SHELL_VARS", {"C"})
    config.load_env_file(tmp_path / ".env")
    config.load_env_file(tmp_path / ".env.demo")
    import os
    assert (os.environ["A"], os.environ["B"], os.environ["C"]) == ("shared", "agent", "shell")


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

def _load_team_source(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"test_{name}", ROOT / "sources" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_athena_page_cleans_to_the_same_text_as_before():
    athena = _load_team_source("athena_mcp")
    page = json.loads((ROOT / "tests/fixtures/athena_page_8708.json").read_text())
    title, text = athena.page_to_text(page)
    assert f"{title}\n\n{text}".strip() == (ROOT / "tests/fixtures/athena_page_8708.txt").read_text().strip()


@pytest.mark.parametrize("event_stream", [False, True])
def test_athena_mcp_source_calls_the_mcp_server(monkeypatch, event_stream):
    page = json.loads((ROOT / "tests/fixtures/athena_page_8708.json").read_text())
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers["x-lbg-client-id"], body["params"]))
            reply = json.dumps({"jsonrpc": "2.0", "id": 1,
                                "result": {"structuredContent": {"result": {"value": page}}}})
            self.send_response(200)
            self.end_headers()
            self.wfile.write((f"event: message\ndata: {reply}\n\n" if event_stream else reply).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HIVE_ATHENA_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("HIVE_ATHENA_CLIENT_ID", "id")
    monkeypatch.setenv("HIVE_ATHENA_CLIENT_SECRET", "secret")
    try:
        documents = _load_team_source("athena_mcp").fetch({}, ["8708"], Path("."))
    finally:
        server.shutdown()
    assert seen == [("/v1/mcp", "id", {"name": "athena_get_page_content",
                                       "arguments": {"pageId": "8708", "format": "json"}})]
    assert documents[0]["text"].startswith("Types of Accessible Format Statements")
    assert documents[0]["metadata"]["revision"] == str(page["@revision"])


@pytest.fixture
def fake_generator(monkeypatch):
    """DeepEval's Synthesizer and the CORTEX model replaced by fakes; records what they were given."""
    import deepeval.synthesizer
    from deepeval.dataset import Golden
    from deepeval.models import DeepEvalBaseLLM

    from evalkit import cortex

    class FakeLLM(DeepEvalBaseLLM):
        def load_model(self):
            return self

        def generate(self, prompt, schema=None):
            return ""

        async def a_generate(self, prompt, schema=None):
            return ""

        def get_model_name(self):
            return "fake-model"

    calls = {"styles": [], "contexts": [], "answer": "Answer from the page.", "input": None, "fail_on": None}

    class FakeSynthesizer:
        def __init__(self, styling_config, **kwargs):
            calls["styles"].append(styling_config)

        def generate_goldens_from_contexts(self, contexts, source_files, max_goldens_per_context, **kwargs):
            if calls["fail_on"] in source_files:
                raise TimeoutError("CORTEX timed out")
            calls["contexts"].append(contexts[0][0])
            number = len(calls["contexts"])
            question = calls["input"] or f"Question {number} about {source_files[0]}?"
            return [Golden(input=question, expected_output=calls["answer"], source_file=source_files[0])
                    for _ in range(max_goldens_per_context)]

    monkeypatch.setattr(cortex, "deepeval_llm", FakeLLM)
    monkeypatch.setattr(deepeval.synthesizer, "Synthesizer", FakeSynthesizer)
    return calls


@pytest.fixture
def ka_copy(tmp_path, monkeypatch):
    """The real knowledge_agent folder in a temp dir, with the two Athena pages already cached."""
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "knowledge_agent", agents / "knowledge_agent")
    monkeypatch.setattr(config, "AGENTS_DIR", agents)
    cache = agents / "knowledge_agent" / "synth" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for page_id in ("36626", "39696"):
        (cache / f"{page_id}.json").write_text(json.dumps({
            "id": page_id, "title": f"Page {page_id}", "text": f"Content of page {page_id}.",
            "group": "", "metadata": {"revision": "7"}}))
    return agents / "knowledge_agent"


def test_goldens_for_the_knowledge_agent(ka_copy, fake_generator):
    from evalkit import synth

    written = synth.generate_goldens("knowledge_agent")
    assert len(written) == 12                                         # 6 styles x 2 pages x 1
    assert "advisor" in fake_generator["styles"][0].scenario.lower()  # instructions.md folded in
    assert "colleague" in fake_generator["styles"][0].task            # additional_guidance folded in

    folder = ka_copy / "testdata/golden/direct_query/recoveries_commercial_bank"
    path = folder / "TC_SYN_direct_query_recoveries_commercial_bank_001.json"
    case = json.loads(path.read_text())
    assert case["input"] == {"question": "Question 1 about 36626?"}
    assert case["expected"] == {"expected_answer": "Answer from the page.", "source_page_id": "36626"}
    assert case["metadata"]["domain"] == "Recoveries Commercial Bank"
    assert case["metadata"]["source_revision"] == "7"
    assert case["metadata"]["approval_status"] == "UNREVIEWED"

    agent = load_agent("knowledge_agent")
    assert len(runner.load_cases(agent, agent.suite("golden"))) == 12   # sub-folders are read
    manifest = json.loads(next((ka_copy / "synth/runs").glob("*.json")).read_text())
    assert manifest["generated"] == 12 and manifest["failed"] == []


def test_goldens_add_to_existing_cases_unless_replace(ka_copy, fake_generator):
    from evalkit import synth

    synth.generate_goldens("knowledge_agent", ids=["36626"])
    fake_generator["contexts"].clear()                     # run again: new cases are numbered after the old ones
    synth.generate_goldens("knowledge_agent", ids=["36626"])
    folder = ka_copy / "testdata/golden/direct_query/recoveries_commercial_bank"
    assert sorted(p.name[-8:] for p in folder.glob("*.json")) == ["001.json", "002.json"]
    synth.generate_goldens("knowledge_agent", ids=["36626"], replace=True)
    assert len(list(folder.glob("*.json"))) == 1


def test_goldens_filters_skips_and_failures(ka_copy, fake_generator):
    from evalkit import synth

    with pytest.raises(ConfigError, match="unknown group"):
        synth.generate_goldens("knowledge_agent", groups=["Blackhorse"])

    fake_generator["fail_on"] = "39696"                     # one page fails: the run carries on
    fake_generator["input"] = "Same question every time?"   # duplicates are dropped
    written = synth.generate_goldens("knowledge_agent", groups=["recoveries commercial bank"])
    assert len(written) == 1
    manifest = json.loads(next((ka_copy / "synth/runs").glob("*.json")).read_text())
    assert len(manifest["failed"]) == 6
    assert {s["reason"] for s in manifest["skipped"]} == {"duplicate question"}


def test_placeholder_answers_are_rejected(ka_copy, fake_generator):
    from evalkit import synth

    fake_generator["answer"] = "The team is [INSERT TEAM NAME]."
    assert synth.generate_goldens("knowledge_agent") == []


def test_any_agent_any_source_any_case_shape(tmp_path, monkeypatch, fake_generator):
    """A different agent: JSON records as the source, and its own test-case shape."""
    from evalkit import synth

    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "_template", agents / "_template")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / ".env.example").write_text("")
    for module in (config, new_agent):
        monkeypatch.setattr(module, "AGENTS_DIR", agents)
    monkeypatch.setattr(new_agent, "ROOT", tmp_path)
    new_agent.create_agent("analysis_agent", input_field="request")
    synth_dir = agents / "analysis_agent" / "synth"
    (synth_dir / "styles").mkdir(parents=True)
    (synth_dir / "styles" / "trend.md").write_text("## task\nAsk for a trend.\n\n## input_format\n"
                                                   'JSON: {"request": "...", "metric": "..."}\n')
    (synth_dir / "sales.json").write_text(json.dumps({"rows": [
        {"sku": "A1", "region": "North", "q1": 10, "q2": 14},
        {"sku": "B2", "region": "South", "q1": 7, "q2": 5}]}))
    (synth_dir / "synth.yaml").write_text("""
source: {type: json_records, file: sales.json, records_key: rows, id_field: sku, group_field: region}
styles: {trend: {file: styles/trend.md, per_source: 1}}
output:
  folder: testdata/golden/{group_slug}
  id: "AN_{source.id}_{n:02}"
  case:
    test_case_id: "{id}"
    input: {request: "{generated.input.request}", dataset: "{source.id}"}
    expected: {metric: "{generated.input.metric}", summary: "{generated.expected_output}"}
""")
    fake_generator["input"] = '{"request": "How did sales move?", "metric": "q2 vs q1"}'
    written = synth.generate_goldens("analysis_agent", groups=["north"])
    case = json.loads(written[0].read_text())
    assert written[0].parent.name == "north"
    assert case == {"test_case_id": "AN_A1_01",
                    "input": {"request": "How did sales move?", "dataset": "A1"},
                    "expected": {"metric": "q2 vs q1", "summary": "Answer from the page."}}
    assert '"q2": 14' in fake_generator["contexts"][0]              # whole record given to the generator

    fake_generator["input"] = "not json"                              # template field missing -> skipped
    assert synth.generate_goldens("analysis_agent", ids=["B2"]) == []


def test_files_source_and_default_case_shape(tmp_path, monkeypatch, fake_generator):
    from evalkit import synth

    agents = tmp_path / "agents"
    folder = agents / "demo" / "synth"
    (folder / "documents" / "Cards").mkdir(parents=True)
    (folder / "documents" / "Cards" / "limits.md").write_text("Card limits\nThe daily limit is 500.")
    (folder / "styles").mkdir()
    (folder / "styles" / "q.md").write_text("## task\nAsk one question.\n")
    (folder / "synth.yaml").write_text("source: {type: files}\nstyles: {q: {file: styles/q.md}}\n")
    (agents / "demo" / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\ninput_field: prompt\n"
        "suites: {golden: {testdata: testdata/golden, only: {metadata.approval_status: APPROVED}}}\n")
    monkeypatch.setattr(config, "AGENTS_DIR", agents)

    written = synth.generate_goldens("demo")
    case = json.loads(written[0].read_text())
    assert written[0].relative_to(agents / "demo").parts[:4] == ("testdata", "golden", "q", "cards")
    assert case["input"] == {"prompt": "Question 1 about limits?"}
    assert case["expected"]["expected_answer"] == "Answer from the page."
    agent = load_agent("demo")
    with pytest.raises(ConfigError, match="matching only"):              # nothing approved yet
        runner.load_cases(agent, agent.suite("golden"))
    case["metadata"]["approval_status"] = "APPROVED"
    written[0].write_text(json.dumps(case))
    assert len(runner.load_cases(agent, agent.suite("golden"))) == 1


def test_synth_config_mistakes_are_caught(ka_copy):
    from evalkit import synth

    style = ka_copy / "synth/styles/conditional_query.md"
    style.write_text(style.read_text().replace("## additional_guidance", "## additional guidance"))
    with pytest.raises(ConfigError, match="unknown section"):
        synth.load_settings(load_agent("knowledge_agent"))
    style.write_text(style.read_text().replace("## additional guidance", "## additional_guidance"))

    settings = ka_copy / "synth/synth.yaml"
    settings.write_text(settings.read_text().replace("REASONING: 0.30", "REASONING: 0.50"))
    with pytest.raises(ConfigError, match="add up to 1.0"):
        synth.load_settings(load_agent("knowledge_agent"))
