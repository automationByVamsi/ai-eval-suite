"""
Shared HTTP/HTTPS transport (stdlib http.client, not `requests`).

Some corporate networks sit behind a TLS-intercepting proxy that `requests`'s
cert verification doesn't tolerate even with verify=False. Passing an
explicitly unverified ssl.SSLContext per-connection (instead of monkeypatching
ssl.create_default_context globally) gets the same compatibility without
weakening TLS for any other code in the process.

Uses HTTPConnection for http:// URLs (local ADK) and HTTPSConnection for
https:// (CORTEX / remote ADK). CortexClient and AdkClient share this so
retry/timeout/TLS behaviour only needs to be right in one place.
"""

from __future__ import annotations

import json
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import Any


def split_host_path(url: str) -> tuple[str, str, str]:
    """
    Parse a base URL into (scheme, host[:port], path_prefix).

    Examples:
      'http://localhost:8080' -> ('http', 'localhost:8080', '')
      'https://host.example.com/v1' -> ('https', 'host.example.com', '/v1')

    URLs without a scheme default to https (safe for cloud gateways).
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is empty")

    if "://" in raw:
        scheme, rest = raw.split("://", 1)
    else:
        scheme, rest = "https", raw

    scheme = scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {scheme!r} (expected http or https)")

    host, _, path_rest = rest.partition("/")
    if not host:
        raise ValueError(f"URL missing host: {url!r}")
    path = f"/{path_rest}" if path_rest else ""
    return scheme, host, path


def post_json(
    host: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    scheme: str = "https",
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """POST a JSON body and return the parsed JSON response (dict or list)."""
    scheme = (scheme or "https").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme {scheme!r}")

    body = json.dumps(payload)
    request_headers = {"Content-Type": "application/json", **headers}

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if scheme == "http":
            conn: HTTPConnection | HTTPSConnection = HTTPConnection(
                host, timeout=timeout_s
            )
        else:
            context = (
                ssl.create_default_context()
                if verify_tls
                else ssl._create_unverified_context()
            )
            conn = HTTPSConnection(host, context=context, timeout=timeout_s)
        try:
            conn.request("POST", path, body, request_headers)
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8")
            if resp.status != 200:
                raise RuntimeError(
                    f"HTTP {resp.status} from {scheme}://{host}{path}: {resp_body[:400]}"
                )
            return json.loads(resp_body) if resp_body else {}
        except Exception as exc:  # noqa: BLE001 - we deliberately retry on any failure
            last_error = exc
            if attempt < retries:
                time.sleep(2**attempt)
        finally:
            conn.close()

    raise RuntimeError(
        f"POST {scheme}://{host}{path} failed after {retries + 1} attempt(s): {last_error}"
    )
