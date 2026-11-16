"""HTTPS certificate settings for every outgoing call, from CA_BUNDLE and VERIFY_TLS in env/.env.

The office proxy re-signs HTTPS, so checks are off by default unless VERIFY_TLS=true or a CA bundle is set.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

_PATCHED = False


def ca_bundle() -> str:
    """Return the corporate CA file path (CA_BUNDLE or legacy CORTEX_CA_BUNDLE), or ""."""
    return (os.environ.get("CA_BUNDLE") or os.environ.get("CORTEX_CA_BUNDLE") or "").strip()


def verify_enabled() -> bool:
    """True if a CA bundle is set or VERIFY_TLS (legacy CORTEX_VERIFY_TLS) is true; False by default."""
    if ca_bundle():
        return True
    value = os.environ.get("VERIFY_TLS") or os.environ.get("CORTEX_VERIFY_TLS") or "false"
    return value.strip().lower() == "true"


def configure() -> None:
    """Apply the TLS settings to the whole process. Safe to call more than once."""
    bundle = ca_bundle()
    if bundle:
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)     # requests (used inside some SDKs)
    elif not verify_enabled():
        _disable_verification_everywhere()


def httpx_verify(setting: Any = True) -> bool | ssl.SSLContext:
    """Return the httpx `verify=` value for a per-client setting (true | false | CA path).
    Always False when checks are off for the whole process."""
    if not verify_enabled():
        return False
    if isinstance(setting, bool):
        return setting
    text = str(setting if setting is not None else "").strip()
    if text.lower() in ("true", "false", ""):
        return text.lower() != "false"
    return ssl.create_default_context(cafile=text)


def _disable_verification_everywhere() -> None:
    """Patch ssl so every new context skips certificate checks, including those created inside SDKs."""
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
