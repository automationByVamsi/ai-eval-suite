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

Pegasus uses its own `cortex_api` adapter (PEGASUS_CORTEX_MODEL picks its model):
  api_key mode  CORTEX_API_KEY (or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET, or PEGASUS_CERT_PATH),
                base URL CORTEX_BASE_URL (default CORTEX_HOST)
  devkit mode   no key needed: get_model(..., auth_token=<client.get_token()>) against the DevKit's
                CorteX address (…/api/v1; CORTEX_BASE_URL overrides it).
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
    """
    Can Pegasus sign its CORTEX calls? In devkit mode: yes, with the DevKit sign-in (see pegasus_llm).
    In api_key mode: it needs an API key, a client id + secret, or a certificate.
    """
    if auth_mode() == "devkit":
        return True
    env = {k: os.environ.get(k, "").strip() for k in
           ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH")}
    return bool(env["CORTEX_API_KEY"] or env["PEGASUS_CERT_PATH"]
                or (env["CORTEX_CLIENT_ID"] and env["CORTEX_CLIENT_SECRET"]))


# --- DevKit sign-in for Pegasus ---------------------------------------------------------------
# Pegasus can't use cortex.Client() — its `cortex_api` adapter only takes an API key. So in devkit mode
# we hand it the same sign-in the DevKit client uses: the CorteX token (from `make cortex-login`) as the
# key, and the DevKit's CorteX address as the base URL. The token is read again for every Pegasus judge,
# so a refreshed token is picked up during long runs.

@functools.cache
def _shared_devkit_client() -> Any:
    return _devkit_client(float(os.environ.get("CORTEX_TIMEOUT_S", "60")))


def devkit_token() -> str:
    """
    The CorteX token for Pegasus (never printed or saved). Asked from the DevKit each time, so the
    DevKit can refresh it (DevKit tokens last ~15 minutes).

    1. client.get_token() — the DevKit's own call for this (CorteX DevKit + Pegasus guidance)
    2. otherwise, the Authorization header the client signs its requests with
    """
    client = _shared_devkit_client()
    for name in ("get_token", "get_access_token"):
        method = getattr(client, name, None)
        if callable(method):
            token = method()
            token = getattr(token, "token", None) or getattr(token, "access_token", None) or token
            if token:
                return _bare_token(str(token))

    headers = getattr(client, "headers", None) or {}
    header = headers.get("Authorization") or headers.get("authorization") or ""
    auth = getattr(client, "auth", None)
    if not header and auth is not None and hasattr(client, "build_request"):
        # httpx-style auth: sign a throw-away request (nothing is sent) and read its header.
        request = client.build_request("POST", _devkit_chat_path(client))
        flow = auth.sync_auth_flow(request)
        try:
            header = next(flow).headers.get("Authorization", "")
        finally:
            flow.close()
    if header:
        return _bare_token(header)
    hints = [a for a in dir(client) if "token" in a.lower() or "auth" in a.lower()]
    raise JudgeConfigError("Could not read the CorteX DevKit sign-in for Pegasus. Run make cortex-login; if it "
                           f"persists, share this list of DevKit client methods: {hints}")


def _bare_token(value: str) -> str:
    """'Bearer abc' -> 'abc'."""
    return value.split(" ", 1)[1] if value.lower().startswith("bearer ") else value


def devkit_api_base() -> str:
    """The DevKit's CorteX API address ending in /v1 — what Pegasus appends /chat/completions to."""
    client = _shared_devkit_client()
    path = os.environ.get("CORTEX_DEVKIT_CHAT_PATH") or _devkit_chat_path(client)
    return (str(getattr(client, "base_url", "")).rstrip("/") + path).removesuffix("/chat/completions")


@functools.cache
def deepeval_llm() -> CortexLLM:
    """One shared CortexLLM per process (one HTTP connection pool for all judges)."""
    return CortexLLM()


def pegasus_llm() -> Any:
    """
    The LLM object Pegasus metrics take, from Pegasus' own `cortex_api` adapter.

    devkit mode:  get_model(..., auth_token=<DevKit token>) against the DevKit's CorteX address
                  (CorteX DevKit + Pegasus guidance). CORTEX_BASE_URL overrides the address.
    api_key mode: CORTEX_API_KEY (CorteX 2.0), or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET, or
                  PEGASUS_CERT_PATH; base URL CORTEX_BASE_URL or CORTEX_HOST.
    """
    model = os.environ.get("PEGASUS_CORTEX_MODEL") or os.environ.get("CORTEX_MODEL") or "gemini-2.5-flash"
    if auth_mode() == "devkit":
        return _pegasus_model(_with_provider(model), os.environ.get("CORTEX_BASE_URL") or devkit_api_base(),
                              auth_token=devkit_token(), ca_cert_path=tls.ca_bundle())
    if not pegasus_can_authenticate():
        raise JudgeConfigError("Pegasus needs CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET in env/.env "
                               "(or use CORTEX_AUTH=devkit)")
    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    return _pegasus_model(
        model if api_key else _with_provider(model),   # the client-id/secret gateway wants the prefix
        os.environ.get("CORTEX_BASE_URL") or require("CORTEX_HOST", JudgeConfigError),
        api_key=api_key,
        client_id=os.environ.get("CORTEX_CLIENT_ID", "").strip(),
        client_secret=os.environ.get("CORTEX_CLIENT_SECRET", "").strip(),
        cert_path=os.environ.get("PEGASUS_CERT_PATH", "").strip(),
    )


def _with_provider(model: str) -> str:
    """gemini-2.5-flash -> vertex_ai/gemini-2.5-flash (already-prefixed names are left alone)."""
    return model if "/" in model else f"vertex_ai/{model}"


@functools.lru_cache(maxsize=4)   # one model per sign-in; a refreshed DevKit token builds a new one
def _pegasus_model(model: str, base_url: str, api_key: str = "", client_id: str = "", client_secret: str = "",
                   cert_path: str = "", auth_token: str = "", ca_cert_path: str = "") -> Any:
    from pegasus.utils.adapters import get_model  # internal package: only imported when Pegasus runs

    kwargs: dict[str, Any] = {
        "adapter": "cortex_api",
        "model_type": "llm",
        "model_name": model,
        "base_url": base_url,
        "ssl_verify": tls.verify_enabled(),
    }
    optional = {"api_key": api_key, "client_id": client_id, "client_secret": client_secret,
                "cert_path": cert_path, "auth_token": auth_token, "ca_cert_path": ca_cert_path}
    kwargs.update({k: v for k, v in optional.items() if v})

    # Pegasus versions differ in which arguments get_model accepts; try the closest variants in turn.
    attempts = [kwargs, {k: v for k, v in kwargs.items() if k != "ssl_verify"}]
    if auth_token:   # a version without auth_token: pass the DevKit token where the API key goes
        without = {k: v for k, v in attempts[-1].items() if k != "auth_token"}
        attempts.append({**without, "api_key": auth_token})
    for i, arguments in enumerate(attempts):
        try:
            return get_model(**arguments)
        except TypeError:
            if i == len(attempts) - 1:
                raise
    raise AssertionError("unreachable")


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
