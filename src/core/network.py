"""
Shared HTTP request utils (stdlib http.client — no `requests`).

Use these for any API call in the suite:

    from src.core.network import get, post, put, patch

    data = get(url, headers=..., params={"format": "json"}, verify_tls=False)
    data = post(url, payload={...}, headers=...)
    data = put(url, payload={...}, headers=...)
    data = patch(url, payload={...}, headers=...)

Legacy helpers `get_json` / `post_json(host, path, ...)` still work for ADK / CORTEX.
"""

from __future__ import annotations

import json
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})


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


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    if verify_tls:
        return ssl.create_default_context()
    ctx = ssl._create_unverified_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _with_params(url: str, params: dict[str, str] | None) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    query = urlencode(params)
    if parsed.query:
        query = f"{parsed.query}&{query}"
    return urlunparse(parsed._replace(query=query))


def request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
    ok_statuses: tuple[int, ...] | None = None,
) -> Any:
    """
    Call an HTTP API and return parsed JSON (or {} if the body is empty).

    `ok_statuses` defaults to any 2xx.
    """
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ValueError(f"Unsupported method {method!r}")

    final_url = _with_params(url.strip(), params)
    parsed = urlparse(final_url)
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
    if method in _METHODS_WITH_BODY:
        body = json.dumps(payload if payload is not None else {})
        request_headers.setdefault("content-type", "application/json")

    allowed = ok_statuses or tuple(range(200, 300))
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
            if resp.status not in allowed:
                raise RuntimeError(
                    f"HTTP {resp.status} from {scheme}://{parsed.netloc}{path}: "
                    f"{resp_body[:400]!r}"
                )
            if not resp_body.strip():
                return {}
            return json.loads(resp_body)
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


# ---------------------------------------------------------------------------
# Simple verbs — prefer these in new code
# ---------------------------------------------------------------------------


def get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """HTTP GET → JSON."""
    return request(
        "GET",
        url,
        headers=headers,
        params=params,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )


def post(
    url: str,
    *,
    payload: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """HTTP POST JSON → JSON."""
    return request(
        "POST",
        url,
        payload=payload,
        headers=headers,
        params=params,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )


def put(
    url: str,
    *,
    payload: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """HTTP PUT JSON → JSON."""
    return request(
        "PUT",
        url,
        payload=payload,
        headers=headers,
        params=params,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )


def patch(
    url: str,
    *,
    payload: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """HTTP PATCH JSON → JSON."""
    return request(
        "PATCH",
        url,
        payload=payload,
        headers=headers,
        params=params,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------


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
    """Alias for request() (older call sites)."""
    return request(
        method,
        url,
        payload=payload,
        headers=headers,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
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
    """Alias for get()."""
    return get(
        url,
        headers=headers,
        params=params,
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
    """POST using host + path (ADK / CORTEX clients). Prefer post(url=...) in new code."""
    scheme = (scheme or "https").lower()
    if not path.startswith("/"):
        path = f"/{path}"
    return post(
        f"{scheme}://{host}{path}",
        payload=payload,
        headers=headers,
        verify_tls=verify_tls,
        timeout_s=timeout_s,
        retries=retries,
    )
