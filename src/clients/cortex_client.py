"""
The judge model: every LLM call (DeepEval judges, Pegasus judges, the synthesizer) goes to the
CORTEX gateway.

  DeepEval judges + synthesizer -> CortexLLM, which POSTs to {CORTEX_HOST}/chat/completions
  Pegasus judges                -> pegasus_llm(), built with Pegasus' own CORTEX adapter

Settings (env/.env — see env/.env.example):
  CORTEX_HOST        gateway URL ending in /v1 (the client adds /chat/completions)
  CORTEX_MODEL       e.g. vertex_ai/gemini-2.5-pro
  CORTEX_CLIENT_ID   sent as x-lbg-origin-client-id
  CORTEX_API_KEY     CorteX 2.0: sent as Authorization: Bearer <key>
  CORTEX_TIMEOUT_S   default 60        CORTEX_RETRIES   default 2 (429 / 5xx / network errors)
  CORTEX_VERIFY_TLS  default true      CORTEX_CA_BUNDLE path to a CA file (better than turning TLS off)
  Pegasus only: CORTEX_BASE_URL (default CORTEX_HOST), CORTEX_CLIENT_SECRET, PEGASUS_CORTEX_MODEL,
                PEGASUS_CERT_PATH
"""

from __future__ import annotations

import functools
import json
import os
import time
from typing import Any

import httpx
from deepeval.models import DeepEvalBaseLLM

from src.core.env import require, tls_setting
from src.core.exceptions import JudgeConfigError
from src.utils.text import strip_code_fence

RETRY_STATUS = {429, 500, 502, 503, 504}   # busy or briefly broken gateway: worth another try


def cortex_headers() -> dict[str, str]:
    """x-lbg-origin-client-id always; Authorization: Bearer <CORTEX_API_KEY> when a key is set."""
    headers = {"x-lbg-origin-client-id": require("CORTEX_CLIENT_ID", JudgeConfigError)}
    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def cortex_verify_tls() -> bool | str:
    """CORTEX_CA_BUNDLE if set, else CORTEX_VERIFY_TLS (default true)."""
    return os.environ.get("CORTEX_CA_BUNDLE") or tls_setting(os.environ.get("CORTEX_VERIFY_TLS", "true"))


class CortexLLM(DeepEvalBaseLLM):
    """A DeepEval model that sends every prompt to CORTEX. Temperature 0, so judging is repeatable."""

    def __init__(self) -> None:
        # DeepEvalBaseLLM.__init__ sets self.model = load_model(), so the model name lives in model_id.
        self.model_id = os.environ.get("CORTEX_MODEL", "vertex_ai/gemini-2.5-pro")
        self.url = require("CORTEX_HOST", JudgeConfigError).rstrip("/") + "/chat/completions"
        self.retries = int(os.environ.get("CORTEX_RETRIES", "2"))
        self.http = httpx.Client(
            timeout=float(os.environ.get("CORTEX_TIMEOUT_S", "60")),
            verify=cortex_verify_tls(),
            headers=cortex_headers(),
        )
        super().__init__(self.model_id)

    def load_model(self) -> CortexLLM:
        return self

    def get_model_name(self) -> str:
        return self.model_id

    def generate(self, prompt: str, schema: Any = None) -> Any:
        """
        Send one prompt, return the text — or, when DeepEval passes a pydantic `schema`, an
        instance of it parsed from the JSON answer.
        """
        body = {"model": self.model_id, "temperature": 0.0, "messages": [{"role": "user", "content": prompt}]}
        response = self._post_with_retries(body)
        text = strip_code_fence(response.json()["choices"][0]["message"]["content"])
        return text if schema is None else _to_schema(text, schema)

    async def a_generate(self, prompt: str, schema: Any = None) -> Any:
        # Judges run with async_mode=False; this exists because DeepEval requires it.
        return self.generate(prompt, schema)

    def _post_with_retries(self, body: dict[str, Any]) -> httpx.Response:
        """POST, retrying RETRY_STATUS answers and network errors with a short back-off (2s, 4s, ...)."""
        for attempt in range(self.retries + 1):
            last_try = attempt == self.retries
            try:
                response = self.http.post(self.url, json=body)
            except httpx.TransportError:
                if last_try:
                    raise
            else:
                if response.status_code not in RETRY_STATUS or last_try:
                    response.raise_for_status()
                    return response
            time.sleep(2 * (attempt + 1))
        raise AssertionError("unreachable")   # the loop always returns or raises


@functools.cache
def deepeval_llm() -> CortexLLM:
    """One shared CortexLLM per process (one HTTP connection pool for all judges)."""
    return CortexLLM()


@functools.cache
def pegasus_llm() -> Any:
    """
    The LLM object Pegasus metrics take, from Pegasus' own `cortex_api` adapter.

    Auth: CORTEX_API_KEY (CorteX 2.0), or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET, or PEGASUS_CERT_PATH.
    """
    from pegasus.utils.adapters import get_model  # internal package: only imported when Pegasus runs

    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    model = os.environ.get("PEGASUS_CORTEX_MODEL") or os.environ.get("CORTEX_MODEL") or "gemini-2.5-flash"
    if not api_key and not model.startswith("vertex_ai/"):
        model = f"vertex_ai/{model}"   # the client-id/secret gateway expects the provider prefix
    kwargs: dict[str, Any] = {
        "adapter": "cortex_api",
        "model_type": "llm",
        "model_name": model,
        "base_url": os.environ.get("CORTEX_BASE_URL") or require("CORTEX_HOST", JudgeConfigError),
        "ssl_verify": cortex_verify_tls() is not False,
    }
    optional = {
        "api_key": api_key,
        "client_id": os.environ.get("CORTEX_CLIENT_ID", ""),
        "client_secret": os.environ.get("CORTEX_CLIENT_SECRET", ""),
        "cert_path": os.environ.get("PEGASUS_CERT_PATH", ""),
    }
    kwargs.update({k: v.strip() for k, v in optional.items() if v.strip()})
    if not (api_key or kwargs.get("cert_path") or (kwargs.get("client_id") and kwargs.get("client_secret"))):
        raise JudgeConfigError("Pegasus needs CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET in env/.env")
    try:
        return get_model(**kwargs)
    except TypeError:  # older Pegasus versions don't accept ssl_verify
        kwargs.pop("ssl_verify")
        return get_model(**kwargs)


def _to_schema(text: str, schema: Any) -> Any:
    """Parse the model's JSON into DeepEval's schema; see the comments for the two fallbacks."""
    try:
        return schema(**json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Schemas with a single `response` field just want the text.
    if set(getattr(schema, "model_fields", {})) == {"response"}:
        return schema(response=text)
    # A TypeError makes DeepEval retry without a schema and parse the JSON itself.
    raise TypeError(f"CORTEX output does not match {schema.__name__}")
