"""Build a Pegasus LLM via CorteX / Apigee adapters."""

from __future__ import annotations

import os
from typing import Any


def build_llm(cortex_client: Any = None):
    """
    Preferred (CorteX 2.0): CORTEX_BASE_URL + CORTEX_API_KEY + PEGASUS_CORTEX_MODEL
    Fallback: CORTEX_HOST + client_id/secret or PEGASUS_CERT_PATH
    """
    from src.core.env import load_dotenv

    load_dotenv()

    from pegasus.utils.adapters import get_model  # type: ignore

    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    if api_key in {"your_api_key_here", "changeme", "TODO"}:
        api_key = ""
    base_url = (
        os.environ.get("CORTEX_BASE_URL", "").strip()
        or getattr(cortex_client, "base_url", None)
        or os.environ.get("CORTEX_HOST", "").strip()
        or None
    )
    model_name = (
        os.environ.get("PEGASUS_CORTEX_MODEL", "").strip()
        or os.environ.get("CORTEX_MODEL", "").strip()
        or getattr(cortex_client, "model", None)
        or "gemini-3.1-lite"
    )
    if not api_key and not str(model_name).startswith("vertex_ai/"):
        model_name = f"vertex_ai/{model_name}"

    client_id = os.environ.get("CORTEX_CLIENT_ID", "").strip()
    client_secret = os.environ.get("CORTEX_CLIENT_SECRET", "").strip()
    cert_path = (
        os.environ.get("PEGASUS_CERT_PATH", "").strip()
        or os.environ.get("CORTEX_CERT_PATH", "").strip()
    )

    kwargs: dict[str, Any] = {
        "adapter": "cortex_api",
        "model_type": "llm",
        "model_name": model_name,
        "ssl_verify": False,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if client_id:
        kwargs["client_id"] = client_id
    if client_secret:
        kwargs["client_secret"] = client_secret
    if cert_path:
        kwargs["cert_path"] = cert_path

    if not (api_key or cert_path or (client_id and client_secret)):
        raise ValueError(
            "Pegasus CORTEX auth missing. For CorteX 2.0 set CORTEX_BASE_URL + "
            "CORTEX_API_KEY (+ optional PEGASUS_CORTEX_MODEL) in .env"
        )

    try:
        return get_model(**kwargs)
    except TypeError:
        kwargs.pop("ssl_verify", None)
        return get_model(**kwargs)
