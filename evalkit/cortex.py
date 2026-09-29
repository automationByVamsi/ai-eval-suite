"""
The judge model. Both engines call the same LLM through the CORTEX gateway.

  DeepEval -> CortexLLM (below), which POSTs to {CORTEX_HOST}/chat/completions
  Pegasus  -> pegasus_llm(), built with Pegasus' own CORTEX adapter

All settings come from .env — see .env.example.
"""

from __future__ import annotations

import functools
import json
import os
from typing import Any

import httpx
from deepeval.models import DeepEvalBaseLLM


class JudgeConfigError(Exception):
    """A CORTEX / Pegasus setting is missing from .env."""


def _require(var: str) -> str:
    value = os.environ.get(var, "").strip()
    if not value:
        raise JudgeConfigError(f"{var} is not set — add it to .env (see .env.example)")
    return value


def _verify_tls() -> bool | str:
    """CORTEX_CA_BUNDLE=/path/to/ca.pem, or CORTEX_VERIFY_TLS=false for local sandboxes."""
    if os.environ.get("CORTEX_CA_BUNDLE"):
        return os.environ["CORTEX_CA_BUNDLE"]
    return os.environ.get("CORTEX_VERIFY_TLS", "true").strip().lower() != "false"


class CortexLLM(DeepEvalBaseLLM):
    """DeepEval-compatible model that sends every prompt to CORTEX."""

    def __init__(self) -> None:
        self.model_id = os.environ.get("CORTEX_MODEL", "vertex_ai/gemini-2.5-pro")
        self.url = _require("CORTEX_HOST").rstrip("/") + "/chat/completions"
        self.http = httpx.Client(
            timeout=90,
            verify=_verify_tls(),
            headers={"x-lbg-origin-client-id": _require("CORTEX_CLIENT_ID")},
        )
        super().__init__(self.model_id)

    def load_model(self) -> "CortexLLM":
        return self

    def get_model_name(self) -> str:
        return self.model_id

    def generate(self, prompt: str, schema: Any = None) -> Any:
        response = self.http.post(self.url, json={
            "model": self.model_id,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": prompt}],
        })
        response.raise_for_status()
        text = _strip_fence(response.json()["choices"][0]["message"]["content"])
        return text if schema is None else _to_schema(text, schema)

    async def a_generate(self, prompt: str, schema: Any = None) -> Any:
        return self.generate(prompt, schema)


@functools.cache
def deepeval_llm() -> CortexLLM:
    return CortexLLM()


@functools.cache
def pegasus_llm() -> Any:
    """Pegasus LLM. CorteX 2.0 (CORTEX_BASE_URL + CORTEX_API_KEY) or client id/secret."""
    from pegasus.utils.adapters import get_model  # internal package, see README

    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    model = os.environ.get("PEGASUS_CORTEX_MODEL") or os.environ.get("CORTEX_MODEL") or "gemini-2.5-flash"
    if not api_key and not model.startswith("vertex_ai/"):
        model = f"vertex_ai/{model}"
    kwargs: dict[str, Any] = {
        "adapter": "cortex_api",
        "model_type": "llm",
        "model_name": model,
        "base_url": os.environ.get("CORTEX_BASE_URL") or _require("CORTEX_HOST"),
        "ssl_verify": _verify_tls() is not False,
    }
    optional = {
        "api_key": api_key,
        "client_id": os.environ.get("CORTEX_CLIENT_ID", ""),
        "client_secret": os.environ.get("CORTEX_CLIENT_SECRET", ""),
        "cert_path": os.environ.get("PEGASUS_CERT_PATH", ""),
    }
    kwargs.update({k: v.strip() for k, v in optional.items() if v.strip()})
    if not (api_key or kwargs.get("cert_path") or (kwargs.get("client_id") and kwargs.get("client_secret"))):
        raise JudgeConfigError("Pegasus needs CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET in .env")
    try:
        return get_model(**kwargs)
    except TypeError:  # older Pegasus versions don't accept ssl_verify
        kwargs.pop("ssl_verify")
        return get_model(**kwargs)


def _strip_fence(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ```."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def _to_schema(text: str, schema: Any) -> Any:
    try:
        return schema(**json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if set(getattr(schema, "model_fields", {})) == {"response"}:
        return schema(response=text)
    # TypeError tells DeepEval to retry without a schema and parse the JSON itself.
    raise TypeError(f"CORTEX output does not match {schema.__name__}")
