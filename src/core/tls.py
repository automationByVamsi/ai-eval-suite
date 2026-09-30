"""
HTTPS certificate checks for every outgoing call (CORTEX, Pegasus, DeepEval, Athena, agents).

Why this exists: on the office network a proxy re-signs HTTPS traffic with the bank's own
certificate. Python doesn't trust that certificate by default, so calls fail with
"SSL: CERTIFICATE_VERIFY_FAILED". Two ways to fix it, in env/.env:

  CA_BUNDLE=/path/to/corporate-ca.pem   Best: trust the corporate certificate. Exported as
                                        SSL_CERT_FILE / REQUESTS_CA_BUNDLE, so every library
                                        (httpx, requests, DeepEval, Pegasus) uses it.
  VERIFY_TLS=false                      Skip certificate checks for the whole process — what
                                        main did (its cortex.yaml had verify_tls: false).
                                        This is the default, so the office setup works as-is.
  VERIFY_TLS=true                       Normal certificate checks (CI, machines without the proxy).

configure() runs once at start-up (from src/core/env.py, right after env/.env is loaded).
Clients call httpx_verify() for their own `verify=` argument.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

_PATCHED = False


def ca_bundle() -> str:
    """The corporate CA file from env/.env, or "". (CORTEX_CA_BUNDLE is the older name.)"""
    return (os.environ.get("CA_BUNDLE") or os.environ.get("CORTEX_CA_BUNDLE") or "").strip()


def verify_enabled() -> bool:
    """False unless VERIFY_TLS=true (CORTEX_VERIFY_TLS is the older name). A CA bundle turns it on."""
    if ca_bundle():
        return True
    value = os.environ.get("VERIFY_TLS") or os.environ.get("CORTEX_VERIFY_TLS") or "false"
    return value.strip().lower() == "true"


def configure() -> None:
    """Apply the settings above to the whole process. Safe to call more than once."""
    bundle = ca_bundle()
    if bundle:
        os.environ.setdefault("SSL_CERT_FILE", bundle)          # httpx, ssl, most libraries
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)     # requests (used inside some SDKs)
    elif not verify_enabled():
        _disable_verification_everywhere()


def httpx_verify(setting: Any = True) -> bool | ssl.SSLContext:
    """
    The `verify=` value for an httpx client.

    `setting` is a per-client value such as `verify_tls:` in agent.yaml: true | false | /path/to/ca.pem.
    When checks are off for the whole process (VERIFY_TLS=false), every client skips them.
    """
    if not verify_enabled():
        return False
    if isinstance(setting, bool):
        return setting
    text = str(setting if setting is not None else "").strip()
    if text.lower() in ("true", "false", ""):
        return text.lower() != "false"
    return ssl.create_default_context(cafile=text)             # a CA bundle path


def _disable_verification_everywhere() -> None:
    """
    Make every new SSL context skip certificate checks, including the ones DeepEval, Pegasus
    and the OpenAI-style clients inside them create — the same patch main used.
    """
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    def unverified_context(*_args: Any, **_kwargs: Any) -> ssl.SSLContext:
        context = ssl._create_unverified_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    ssl.create_default_context = unverified_context  # type: ignore[assignment]
    try:  # don't print an "unverified HTTPS request" warning on every call
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        pass
