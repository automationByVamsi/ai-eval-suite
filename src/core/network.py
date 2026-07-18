"""
Shared HTTPS transport (stdlib http.client, not `requests`) - some corporate
networks sit behind a TLS-intercepting proxy that `requests`'s cert
verification doesn't tolerate even with verify=False.
Passing an explicitly unverified ssl.SSLContext per-connection (instead of
monkeypatching ssl.create_default_context globally) gets the same
compatibility without weakening TLS for any other code in the process.

Both CortexClient and ADKAgentAdapter share this so retry/timeout/TLS
behavior only needs to be right in one place.
"""

import json
import ssl
import time
from http.client import HTTPSConnection
from typing import Any


def split_host_path(url: str) -> tuple[str, str]:
    """'https://host.example.com/some/base' -> ('host.example.com', '/some/base')."""
    stripped = url.split("://", 1)[-1]
    host, _, rest = stripped.partition("/")
    return host, f"/{rest}" if rest else ""


def post_json(
    host: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    verify_tls: bool = True,
    timeout_s: float = 30,
    retries: int = 0,
) -> Any:
    """POST a JSON body over HTTPS and return the parsed JSON response (dict or list)."""
    context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
    body = json.dumps(payload)
    request_headers = {"Content-Type": "application/json", **headers}

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        conn = HTTPSConnection(host, context=context, timeout=timeout_s)
        try:
            conn.request("POST", path, body, request_headers)
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8")
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} from {host}{path}: {resp_body[:400]}")
            return json.loads(resp_body) if resp_body else {}
        except Exception as exc:  # noqa: BLE001 - we deliberately retry on any failure
            last_error = exc
            if attempt < retries:
                time.sleep(2**attempt)
        finally:
            conn.close()

    raise RuntimeError(f"POST {host}{path} failed after {retries + 1} attempt(s): {last_error}")
