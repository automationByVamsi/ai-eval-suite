"""Shared test fixtures. Tests never call a real agent, CORTEX or Athena: runs replay saved traces
and HTTP services are local fake servers."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.core import paths

ROOT = paths.ROOT


def serve(handler_class):
    """Start a local HTTP server on a free port; returns (server, base_url). Call server.shutdown()."""
    handler_class.log_message = lambda *args: None          # keep test output quiet
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


# Fake versions of the Athena pages cited by the committed traces.
FAKE_PAGES = {
    "40345": "How To Add a Support Need in MCP",
    "40017": "How to Add a Support Need",
    "40015": "Consent Needed for Adding Support Needs",
    "40022": "Third-Party Consent for Customer Vulnerability Support Needs",
}
KA_LOOKUP = "get_page_content_from_athena"


def fake_athena_page(page_id):
    """Return a fake Athena page from FAKE_PAGES; raise if the id is unknown."""
    if page_id not in FAKE_PAGES:
        raise RuntimeError(f"Athena page {page_id}: not found")
    return {"title": FAKE_PAGES[page_id], "text": f"Text of page {page_id}.", "revision": "1"}


def use_lookup(monkeypatch, fake):
    """Make every lookups.py function call `fake(id)` instead of the network."""
    from src.fields import lookup
    monkeypatch.setattr(lookup, "function", lambda folder, name: fake)


@pytest.fixture(autouse=True)
def no_real_athena(monkeypatch):
    """For every test, serve lookups from FAKE_PAGES and clear the lookup cache."""
    from src.fields import lookup
    lookup.clear_cache()
    use_lookup(monkeypatch, fake_athena_page)
    yield
    lookup.clear_cache()


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Temp outputs/ and baselines/, seeded with the committed traces and their saved evidence pages
    so offline runs work."""
    shutil.copytree(ROOT / "outputs" / "traces", tmp_path / "outputs" / "traces")
    saved = tmp_path / "outputs" / "lookups" / "knowledge_agent" / KA_LOOKUP
    saved.mkdir(parents=True)
    for page_id in FAKE_PAGES:
        (saved / f"{page_id}.json").write_text(json.dumps({"id": page_id, "value": fake_athena_page(page_id)}))
    monkeypatch.setattr(paths, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(paths, "BASELINES_DIR", tmp_path / "baselines")
    return tmp_path


@pytest.fixture
def temp_agents(tmp_path, monkeypatch):
    """Temp agents/ (template only) and env/ folders, for creating agents."""
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "_template", agents / "_template")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / ".env.example").write_text("")
    monkeypatch.setattr(paths, "AGENTS_DIR", agents)
    monkeypatch.setattr(paths, "ENV_DIR", tmp_path / "env")
    return agents


@pytest.fixture
def fake_cortex(monkeypatch):
    """Fake CORTEX gateway that answers every judge prompt favourably, after one 503 to test retries.
    Yields the request headers it saw."""
    from src.clients import cortex_client
    from src.metrics import judges

    reply = {"statements": ["s"], "verdicts": [{"verdict": "yes", "reason": "ok"}], "truths": ["t"],
             "claims": ["c"], "steps": ["check the answer"], "score": 9, "reason": "looks right"}
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append({k.lower(): v for k, v in self.headers.items()})
            if len(seen) == 1:
                self.send_response(503)
                self.end_headers()
                return
            body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server, url = serve(Handler)
    monkeypatch.setenv("CORTEX_HOST", f"{url}/v1")
    monkeypatch.setenv("CORTEX_CLIENT_ID", "test")
    monkeypatch.setenv("CORTEX_API_KEY", "key-123")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    monkeypatch.setattr(cortex_client.time, "sleep", lambda s: None)   # don't wait between retries
    cortex_client.deepeval_llm.cache_clear()
    yield seen
    server.shutdown()
    cortex_client.deepeval_llm.cache_clear()


@pytest.fixture
def fake_generator(monkeypatch):
    """Replace DeepEval's Synthesizer and the CORTEX model with fakes; returns what they were given."""
    import deepeval.synthesizer
    from deepeval.dataset import Golden
    from deepeval.models import DeepEvalBaseLLM

    from src.clients import cortex_client

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
        def __init__(self, styling_config, evolution_config=None, **kwargs):
            calls["styles"].append(styling_config)
            calls.setdefault("evolutions", []).append(evolution_config)

        def generate_goldens_from_contexts(self, contexts, source_files, max_goldens_per_context, **kwargs):
            if calls["fail_on"] in source_files:
                raise TimeoutError("CORTEX timed out")
            calls["contexts"].append(contexts[0][0])
            number = len(calls["contexts"])
            question = calls["input"] or f"Question {number} about {source_files[0]}?"
            return [Golden(input=question, expected_output=calls["answer"], source_file=source_files[0])
                    for _ in range(max_goldens_per_context)]

    monkeypatch.setattr(cortex_client, "deepeval_llm", FakeLLM)
    monkeypatch.setattr(deepeval.synthesizer, "Synthesizer", FakeSynthesizer)
    return calls


@pytest.fixture
def ka_copy(tmp_path, monkeypatch):
    """A temp copy of the knowledge_agent folder, with its two Athena pages already cached."""
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "knowledge_agent", agents / "knowledge_agent")
    monkeypatch.setattr(paths, "AGENTS_DIR", agents)
    cache = agents / "knowledge_agent" / "synth" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for page_id in ("36626", "39696"):
        (cache / f"{page_id}.json").write_text(json.dumps({
            "id": page_id, "title": f"Page {page_id}", "text": f"Content of page {page_id}.",
            "group": "", "metadata": {"revision": "7"}}))
    return agents / "knowledge_agent"
