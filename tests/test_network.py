"""Unit tests for HTTP/HTTPS URL parsing and plain-HTTP POST."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.core.network import post_json, split_host_path


def test_split_http_localhost():
    scheme, host, path = split_host_path("http://localhost:8080")
    assert scheme == "http"
    assert host == "localhost:8080"
    assert path == ""


def test_split_https_with_base_path():
    scheme, host, path = split_host_path(
        "https://example.com/cct1/hive1/hive-complaints-agent"
    )
    assert scheme == "https"
    assert host == "example.com"
    assert path == "/cct1/hive1/hive-complaints-agent"


def test_split_bare_host_defaults_to_https():
    scheme, host, path = split_host_path("gateway.example.com/v1")
    assert scheme == "https"
    assert host == "gateway.example.com"
    assert path == "/v1"


def test_split_rejects_bad_scheme():
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        split_host_path("ftp://example.com")


def test_post_json_over_http():
    """Local ADK speaks plain HTTP — must not use TLS."""
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received["path"] = self.path
            received["body"] = json.loads(body.decode("utf-8"))
            payload = json.dumps({"id": "sess-1"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = post_json(
            f"127.0.0.1:{port}",
            "/apps/knowledge_agent/users/eval_user/sessions",
            {},
            {},
            scheme="http",
            retries=0,
            timeout_s=5,
        )
        assert data == {"id": "sess-1"}
        assert received["path"].endswith("/sessions")
    finally:
        server.shutdown()
