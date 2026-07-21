"""
HTTPS client for Fact Find ground-truth API calls.

Supports optional mTLS (APIC) and verify_tls=False for corporate proxies,
matching the Playwright request.newContext({ ignoreHTTPSErrors, clientCertificates }).
"""

from __future__ import annotations

import json
import ssl
import time
from http.client import HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class FactFindHttpClient:
    def __init__(
        self,
        *,
        cert_paths: tuple[Path, Path] | None = None,
        verify_tls: bool = False,
        timeout_s: float = 60,
        retries: int = 1,
    ):
        self.cert_paths = cert_paths
        self.verify_tls = verify_tls
        self.timeout_s = timeout_s
        self.retries = retries

    def _ssl_context(self, host: str) -> ssl.SSLContext:
        context = ssl.create_default_context() if self.verify_tls else ssl._create_unverified_context()
        if self.cert_paths and self._needs_mtls(host):
            cert, key = self.cert_paths
            context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        return context

    @staticmethod
    def _needs_mtls(host: str) -> bool:
        # Client certs are for APIC; Nucleus ICA proxy typically does not use them.
        host_l = host.lower()
        if "nucleus" in host_l:
            return False
        return "apic" in host_l or "lloydsbanking.cloud" in host_l

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"Only https URLs are supported, got {url}")
        host = parsed.hostname or ""
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        port = parsed.port or 443
        body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request_headers = dict(headers or {})
        if body is not None and "content-type" not in {k.lower() for k in request_headers}:
            request_headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            conn = HTTPSConnection(host, port=port, context=self._ssl_context(host), timeout=self.timeout_s)
            try:
                conn.request(method.upper(), path, body=body, headers=request_headers)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8")
                if resp.status < 200 or resp.status >= 300:
                    raise RuntimeError(f"HTTP {resp.status} from {method} {url}: {raw[:500]}")
                if not raw:
                    return {}
                return json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2**attempt)
            finally:
                conn.close()
        raise RuntimeError(f"{method} {url} failed after {self.retries + 1} attempt(s): {last_error}")

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
        return self.request("GET", url, headers=headers)

    def post(self, url: str, *, headers: dict[str, str] | None = None, json_body: Any = None) -> Any:
        return self.request("POST", url, headers=headers, json_body=json_body)
