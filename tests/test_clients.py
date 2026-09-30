"""HTTP clients: CORTEX retries and auth, Athena MCP calls and page clean-up."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest
from conftest import ROOT, serve

from src.clients import cortex_client
from src.core.exceptions import JudgeConfigError
from src.synthesizer.sources import athena_mcp


def test_cortex_retries_a_busy_gateway_then_answers(fake_cortex):
    assert cortex_client.deepeval_llm().generate("hello")      # first reply is a 503
    assert len(fake_cortex) == 2


def test_cortex_gives_up_after_the_configured_retries(fake_cortex, monkeypatch):
    monkeypatch.setenv("CORTEX_RETRIES", "0")
    cortex_client.deepeval_llm.cache_clear()
    with pytest.raises(Exception, match="503"):
        cortex_client.deepeval_llm().generate("hello")


def test_cortex_without_api_key_sends_only_the_client_id(fake_cortex, monkeypatch):
    monkeypatch.delenv("CORTEX_API_KEY")
    assert cortex_client.cortex_headers() == {"x-lbg-origin-client-id": "test"}
    monkeypatch.delenv("CORTEX_CLIENT_ID")
    with pytest.raises(JudgeConfigError, match="CORTEX_CLIENT_ID"):
        cortex_client.cortex_headers()


def test_athena_page_cleans_to_the_same_text_as_before():
    page = json.loads((ROOT / "tests/fixtures/athena_page_8708.json").read_text())
    title, text = athena_mcp.page_to_text(page)
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

    server, url = serve(Handler)
    monkeypatch.setenv("HIVE_ATHENA_BASE_URL", url)
    monkeypatch.setenv("HIVE_ATHENA_CLIENT_ID", "id")
    monkeypatch.setenv("HIVE_ATHENA_CLIENT_SECRET", "secret")
    try:
        documents = athena_mcp.fetch({}, ["8708"], Path("."))
    finally:
        server.shutdown()
    assert seen == [("/v1/mcp", "id", {"name": "athena_get_page_content",
                                       "arguments": {"pageId": "8708", "format": "json"}})]
    assert documents[0]["text"].startswith("Types of Accessible Format Statements")
    assert documents[0]["metadata"]["revision"] == str(page["@revision"])
