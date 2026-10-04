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


# --- HTTPS certificates (src/core/tls.py) -----------------------------------------------------

def test_certificate_checks_are_off_by_default_like_main(monkeypatch):
    import ssl

    from src.core import tls
    monkeypatch.setattr(tls.os, "environ", {})                     # no VERIFY_TLS / CA_BUNDLE set
    monkeypatch.setattr(tls, "_PATCHED", False)
    monkeypatch.setattr(ssl, "create_default_context", ssl.create_default_context)   # restored after
    tls.configure()
    assert ssl.create_default_context().verify_mode == ssl.CERT_NONE   # DeepEval / Pegasus clients too
    assert tls.httpx_verify(True) is False


def test_ca_bundle_is_shared_with_every_library(monkeypatch, tmp_path):
    from src.core import tls
    bundle = str(tmp_path / "corporate-ca.pem")
    environ = {"CA_BUNDLE": bundle}
    monkeypatch.setattr(tls.os, "environ", environ)
    tls.configure()
    assert environ["SSL_CERT_FILE"] == bundle and environ["REQUESTS_CA_BUNDLE"] == bundle
    assert tls.verify_enabled()


def test_verify_tls_true_keeps_checks_on(monkeypatch):
    from src.core import tls
    monkeypatch.setattr(tls.os, "environ", {"VERIFY_TLS": "true"})
    assert tls.httpx_verify(True) is True and tls.httpx_verify("false") is False


# --- make doctor ------------------------------------------------------------------------------

def test_doctor_reports_pegasus_and_reaches_cortex(fake_cortex, monkeypatch, tmp_path, capsys):
    from src.core import paths
    from src.onboarding.doctor import run_doctor
    (tmp_path / ".env").write_text("")
    monkeypatch.setattr(paths, "ENV_DIR", tmp_path)
    assert run_doctor() == 0                                         # Pegasus missing is a warning
    out = capsys.readouterr().out
    assert "[WARN] pegasus" in out and "[OK  ] CORTEX call" in out
    assert "key-123" not in out                                      # secrets are never printed


def test_doctor_scores_one_pegasus_metric(fake_cortex, monkeypatch, tmp_path, capsys):
    from src.core import paths
    from src.metrics import judges
    from src.onboarding import doctor
    (tmp_path / ".env").write_text("")
    monkeypatch.setattr(paths, "ENV_DIR", tmp_path)
    monkeypatch.setattr(doctor, "_installed", lambda module: True)            # pretend Pegasus is installed
    monkeypatch.setattr(doctor, "_version_of_module", lambda module: "2.5.1")
    monkeypatch.setattr(judges, "score_with_pegasus", lambda metric, values, threshold: (0.93, ""))
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    assert doctor.run_doctor() == 0
    assert "[OK  ] Pegasus metric         relevance score=0.93 [pegasus]" in capsys.readouterr().out


@pytest.mark.parametrize("base", ["https://h/athena-mcp-server", "https://h/athena-mcp-server/",
                                  "https://h/athena-mcp-server/v1/mcp"])
def test_athena_url_with_or_without_v1_mcp(monkeypatch, base):
    from src.clients.athena_client import mcp_url
    monkeypatch.setenv("HIVE_ATHENA_BASE_URL", base)
    assert mcp_url() == "https://h/athena-mcp-server/v1/mcp"


def test_unreachable_cortex_says_where_it_tried(monkeypatch):
    import httpx
    import pytest

    from src.clients import cortex_client

    monkeypatch.setenv("CORTEX_AUTH", "api_key")
    monkeypatch.setenv("CORTEX_HOST", "https://cortex.example.invalid/v1")
    monkeypatch.setenv("CORTEX_RETRIES", "0")
    monkeypatch.setenv("CORTEX_CLIENT_ID", "test-client")
    monkeypatch.setenv("CORTEX_API_KEY", "test-key")
    llm = cortex_client.CortexLLM()

    def boom(*args, **kwargs):
        raise httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")

    monkeypatch.setattr(llm.http, "post", boom)
    where = r"could not reach CORTEX at https://cortex\.example\.invalid/v1/chat/completions"
    with pytest.raises(ConnectionError, match=where):
        llm.generate("hi")
