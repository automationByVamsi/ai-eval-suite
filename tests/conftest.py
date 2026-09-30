"""
Shared test fixtures. The tests never call a real agent, CORTEX or Athena: runs replay the
traces in outputs/traces/, and the HTTP services are small local fake servers.

    make test
"""

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


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Run everything in a temp outputs/ + baselines/, seeded with the committed traces."""
    shutil.copytree(ROOT / "outputs" / "traces", tmp_path / "outputs" / "traces")
    monkeypatch.setattr(paths, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(paths, "BASELINES_DIR", tmp_path / "baselines")
    return tmp_path


@pytest.fixture
def temp_agents(tmp_path, monkeypatch):
    """An empty agents/ (with the template) and env/ in a temp folder, for creating agents."""
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents" / "_template", agents / "_template")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / ".env.example").write_text("")
    monkeypatch.setattr(paths, "AGENTS_DIR", agents)
    monkeypatch.setattr(paths, "ENV_DIR", tmp_path / "env")
    return agents


@pytest.fixture
def fake_cortex(monkeypatch):
    """
    A local stand-in for the CORTEX gateway that answers every judge prompt favourably.
    The first request gets a 503, so the client's retry is exercised. Yields the request headers seen.
    """
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
    """DeepEval's Synthesizer and the CORTEX model replaced by fakes; records what they were given."""
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

    monkeypatch.setattr(cortex_client, "deepeval_llm", FakeLLM)
    monkeypatch.setattr(deepeval.synthesizer, "Synthesizer", FakeSynthesizer)
    return calls


@pytest.fixture
def ka_copy(tmp_path, monkeypatch):
    """The real knowledge_agent folder in a temp dir, with its two Athena pages already cached."""
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
