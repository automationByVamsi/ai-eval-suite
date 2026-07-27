"""
Shared HTTP helpers (stdlib http.client — no `requests`).

Simple rule: give a full URL, get JSON back.

  get_json(url, headers=..., verify_tls=False)
  post_json(host, path, payload, headers=...)   # kept for ADK / CORTEX callers
"""

from __future__ import annotations

import json
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse


def split_host_path(url: str) -> tuple[str, str, str]:
    """
    Parse a base URL into (scheme, host[:port], path_prefix).

    Examples:
      'http://localhost:8080' -> ('http', 'localhost:8080', '')
      'https://host.example.com/v1' -> ('https', 'host.example.com', '/v1')
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


def _ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    if verify_tls:
        return ssl.create_default_context()
    ctx = ssl._create_unverified_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """
    HTTP GET/POST a URL and return parsed JSON.

    `url` is a full URL, e.g. https://host/path?format=json
    """
    method = (method or "GET").upper()
    if method not in ("GET", "POST"):
        raise ValueError(f"Unsupported method {method!r} (use GET or POST)")

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {scheme!r}")
    if not parsed.netloc:
        raise ValueError(f"URL missing host: {url!r}")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    request_headers = dict(headers or {})
    body: str | None = None
    if method == "POST":
        body = json.dumps(payload or {})
        request_headers.setdefault("content-type", "application/json")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if scheme == "http":
            conn: HTTPConnection | HTTPSConnection = HTTPConnection(
                parsed.netloc, timeout=timeout_s
            )
        else:
            conn = HTTPSConnection(
                parsed.netloc,
                context=_ssl_context(verify_tls),
                timeout=timeout_s,
            )
        try:
            conn.request(method, path, body, request_headers)
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8")
            if resp.status != 200:
                raise RuntimeError(
                    f"HTTP {resp.status} from {scheme}://{parsed.netloc}{path}: "
                    f"{resp_body[:400]!r}"
                )
            return json.loads(resp_body) if resp_body else {}
        except Exception as exc:  # noqa: BLE001 - retry on any failure
            last_error = exc
            if attempt < retries:
                time.sleep(2**attempt)
        finally:
            conn.close()

    raise RuntimeError(
        f"{method} {scheme}://{parsed.netloc}{path} failed after "
        f"{retries + 1} attempt(s): {last_error}"
    )


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """GET a full URL (optional query `params`) and return parsed JSON."""
    final_url = url
    if params:
        parsed = urlparse(url)
        query = urlencode(params)
        if parsed.query:
            query = f"{parsed.query}&{query}"
        final_url = urlunparse(parsed._replace(query=query))
    return request_json(
        "GET",
        final_url,
        headers=headers,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )


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
    """POST a JSON body (host + path form used by ADK / CORTEX clients)."""
    scheme = (scheme or "https").lower()
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{scheme}://{host}{path}"
    return request_json(
        "POST",
        url,
        payload=payload,
        headers=headers,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )
