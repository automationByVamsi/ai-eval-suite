"""
The judge model: every LLM call (DeepEval judges, Pegasus judges, the synthesizer) goes to CORTEX.

  DeepEval judges + synthesizer -> CortexLLM (below)
  Pegasus judges                -> pegasus_llm(), built with Pegasus' own CORTEX adapter

Two ways to reach CORTEX — pick one with CORTEX_AUTH in env/.env:

  CORTEX_AUTH=api_key (default)   Call {CORTEX_HOST}/chat/completions directly with:
                                    CORTEX_CLIENT_ID  sent as x-lbg-origin-client-id
                                    CORTEX_API_KEY    sent as Authorization: Bearer <key>
  CORTEX_AUTH=devkit              Use the CorteX DevKit (package cortex-devkit, `import cortex`).
                                  No API key: run `make cortex-login` once (`cx auth login`, SSO in the
                                  browser); cortex.Client() then signs every call. The DevKit finds the
                                  CorteX host itself; CORTEX_ENV=int|pre|prd pins one.
                                  The chat path is worked out from the DevKit's base address
                                  (…/api -> /v1/chat/completions); CORTEX_DEVKIT_CHAT_PATH overrides it.

Both: CORTEX_MODEL (e.g. vertex_ai/gemini-2.5-pro), CORTEX_TIMEOUT_S (60), CORTEX_RETRIES (2: retries on
429 / 5xx / network errors). Certificate checks: VERIFY_TLS / CA_BUNDLE (src/core/tls.py).

Pegasus uses its own adapter and needs CORTEX_API_KEY (or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET, or
PEGASUS_CERT_PATH); CORTEX_BASE_URL (default CORTEX_HOST), PEGASUS_CORTEX_MODEL. In DevKit mode without
those, Pegasus metrics run on DeepEval (through the DevKit) and a warning says so.
"""

from __future__ import annotations

import functools
import json
import os
import time
from typing import Any

import httpx
from deepeval.models import DeepEvalBaseLLM

from src.core import tls
from src.core.env import require
from src.core.exceptions import JudgeConfigError
from src.utils.text import strip_code_fence

RETRY_STATUS = {429, 500, 502, 503, 504}   # busy or briefly broken gateway: worth another try

# DeepEval (and ragas inside Pegasus) insist an OpenAI key exists even when, as here, every call goes
# to CORTEX. A placeholder stops them failing at start-up; it is never sent anywhere. (main did the same.)
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used-all-calls-go-to-cortex")


def cortex_headers() -> dict[str, str]:
    """x-lbg-origin-client-id always; Authorization: Bearer <CORTEX_API_KEY> when a key is set."""
    headers = {"x-lbg-origin-client-id": require("CORTEX_CLIENT_ID", JudgeConfigError)}
    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def auth_mode() -> str:
    """'api_key' (default) or 'devkit', from CORTEX_AUTH in env/.env."""
    mode = (os.environ.get("CORTEX_AUTH") or "api_key").strip().lower()
    if mode not in ("api_key", "devkit"):
        raise JudgeConfigError(f"CORTEX_AUTH must be api_key or devkit, not {mode!r} (env/.env)")
    return mode


class CortexLLM(DeepEvalBaseLLM):
    """A DeepEval model that sends every prompt to CORTEX. Temperature 0, so judging is repeatable."""

    def __init__(self) -> None:
        # DeepEvalBaseLLM.__init__ sets self.model = load_model(), so the model name lives in model_id.
        self.model_id = os.environ.get("CORTEX_MODEL", "vertex_ai/gemini-2.5-pro")
        self.retries = int(os.environ.get("CORTEX_RETRIES", "2"))
        timeout = float(os.environ.get("CORTEX_TIMEOUT_S", "60"))
        self.mode = auth_mode()
        if self.mode == "devkit":
            self.http = _devkit_client(timeout)
            self.url = os.environ.get("CORTEX_DEVKIT_CHAT_PATH") or _devkit_chat_path(self.http)
        else:
            self.url = require("CORTEX_HOST", JudgeConfigError).rstrip("/") + "/chat/completions"
            self.http = httpx.Client(timeout=timeout, verify=tls.httpx_verify(), headers=cortex_headers())
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

    def _post_with_retries(self, body: dict[str, Any]) -> Any:
        """
        POST the chat request, retrying RETRY_STATUS answers and network errors with a short back-off
        (2s, 4s, ...). Same for both modes: the DevKit client is called exactly like an httpx client.
        """
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


def _devkit_client(timeout: float) -> Any:
    """
    cortex.Client() from the CorteX DevKit — an HTTP client that is already signed in (after
    `make cortex-login` locally; automatically on GCP). Called like httpx: .post(path, json=...).
    """
    try:
        import cortex  # package cortex-devkit, from SAR — installed by make setup
    except ImportError as exc:
        raise JudgeConfigError("CORTEX_AUTH=devkit, but the CorteX DevKit isn't installed. "
                               "Run make setup (needs the SAR token in env/.env).") from exc
    try:
        return cortex.Client(timeout=timeout)
    except TypeError:   # a DevKit version without the timeout argument
        return cortex.Client()


def _devkit_chat_path(client: Any) -> str:
    """
    The chat endpoint, relative to the host the DevKit client already points at. The DevKit's base
    address ends in /api on the LBG hosts (…/api + /v1/chat/completions); this also copes with a base
    that already ends in /v1, or a bare host. CORTEX_DEVKIT_CHAT_PATH in env/.env overrides it.
    """
    base = str(getattr(client, "base_url", "") or "").rstrip("/")
    if base.endswith("/v1"):
        return "/chat/completions"
    if base and not base.endswith("/api") and base.count("/") <= 2:   # bare host, e.g. https://cortex…cloud
        return "/api/v1/chat/completions"
    return "/v1/chat/completions"


def pegasus_can_authenticate() -> bool:
    """Pegasus has its own CORTEX adapter: it needs an API key, a client id + secret, or a certificate."""
    env = {k: os.environ.get(k, "").strip() for k in
           ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH")}
    return bool(env["CORTEX_API_KEY"] or env["PEGASUS_CERT_PATH"]
                or (env["CORTEX_CLIENT_ID"] and env["CORTEX_CLIENT_SECRET"]))


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
        "ssl_verify": tls.verify_enabled(),
    }
    optional = {
        "api_key": api_key,
        "client_id": os.environ.get("CORTEX_CLIENT_ID", ""),
        "client_secret": os.environ.get("CORTEX_CLIENT_SECRET", ""),
        "cert_path": os.environ.get("PEGASUS_CERT_PATH", ""),
    }
    kwargs.update({k: v.strip() for k, v in optional.items() if v.strip()})
    if not pegasus_can_authenticate():
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
