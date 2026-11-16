"""LLM clients for CORTEX: CortexLLM for DeepEval judges and the synthesizer, pegasus_llm() for Pegasus judges.

CORTEX_AUTH in env/.env picks api_key (default) or devkit (CorteX DevKit sign-in via `make cortex-login`).
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

# DeepEval and ragas require an OpenAI key to exist; this placeholder is never sent.
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used-all-calls-go-to-cortex")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")   # also for the synthesizer, which never imports judges


def cortex_headers() -> dict[str, str]:
    """Return the CORTEX client-id header, plus a Bearer Authorization header when CORTEX_API_KEY is set."""
    headers = {"x-lbg-origin-client-id": require("CORTEX_CLIENT_ID", JudgeConfigError)}
    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def auth_mode() -> str:
    """Return 'api_key' (default) or 'devkit' from CORTEX_AUTH; raises JudgeConfigError otherwise."""
    mode = (os.environ.get("CORTEX_AUTH") or "api_key").strip().lower()
    if mode not in ("api_key", "devkit"):
        raise JudgeConfigError(f"CORTEX_AUTH must be api_key or devkit, not {mode!r} (env/.env)")
    return mode


class CortexLLM(DeepEvalBaseLLM):
    """A DeepEval model that sends every prompt to CORTEX."""

    def __init__(self) -> None:
        """Set up the HTTP client and chat URL for the configured auth mode."""
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
        """Return self; DeepEval stores this as self.model."""
        return self

    def get_model_name(self) -> str:
        """Return the CORTEX model name."""
        return self.model_id

    def target(self) -> str:
        """Return the full URL chat requests go to."""
        base = str(getattr(self.http, "base_url", "") or "").rstrip("/")
        return self.url if self.url.startswith("http") else f"{base}{self.url}"

    def generate(self, prompt: str, schema: Any = None) -> Any:
        """Send one prompt and return the text, or an instance of `schema` parsed from the JSON answer."""
        from src.metrics.library import judge_temperature
        body = {"model": self.model_id, "temperature": judge_temperature(),
                "messages": [{"role": "user", "content": prompt}]}
        response = self._post_with_retries(body)
        text = strip_code_fence(response.json()["choices"][0]["message"]["content"])
        return text if schema is None else _to_schema(text, schema)

    async def a_generate(self, prompt: str, schema: Any = None) -> Any:
        """Async wrapper DeepEval requires; judges run with async_mode=False."""
        return self.generate(prompt, schema)

    def _post_with_retries(self, body: dict[str, Any]) -> Any:
        """POST the chat request, retrying RETRY_STATUS answers and network errors with a growing back-off."""
        for attempt in range(self.retries + 1):
            last_try = attempt == self.retries
            try:
                response = self.http.post(self.url, json=body)
            except httpx.TransportError as exc:
                if last_try:   # name the URL: a DNS error alone doesn't say which setting is wrong
                    raise ConnectionError(f"could not reach CORTEX at {self.target()} ({self.mode} mode): "
                                          f"{type(exc).__name__}: {exc}") from exc
            else:
                if response.status_code not in RETRY_STATUS or last_try:
                    response.raise_for_status()
                    return response
            time.sleep(2 * (attempt + 1))
        raise AssertionError("unreachable")   # the loop always returns or raises


def _devkit_client(timeout: float) -> Any:
    """Return a signed-in cortex.Client() from the CorteX DevKit; it is called like an httpx client.
    Raises JudgeConfigError if the DevKit isn't installed."""
    try:
        import cortex  # package cortex-devkit, installed by make setup
    except ImportError as exc:
        raise JudgeConfigError("CORTEX_AUTH=devkit, but the CorteX DevKit isn't installed. "
                               "Run make setup (needs the SAR token in env/.env).") from exc
    try:
        return cortex.Client(timeout=timeout)
    except TypeError:   # a DevKit version without the timeout argument
        return cortex.Client()


def _devkit_chat_path(client: Any) -> str:
    """Return the chat path relative to the DevKit client's base address (/api, /v1, or a bare host)."""
    base = str(getattr(client, "base_url", "") or "").rstrip("/")
    if base.endswith("/v1"):
        return "/chat/completions"
    if base and not base.endswith("/api") and base.count("/") <= 2:   # bare host, e.g. https://cortex…cloud
        return "/api/v1/chat/completions"
    return "/v1/chat/completions"


def pegasus_can_authenticate() -> bool:
    """True if Pegasus can sign its CORTEX calls: always in devkit mode, else with a key, id + secret, or cert."""
    if auth_mode() == "devkit":
        return True
    env = {k: os.environ.get(k, "").strip() for k in
           ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH")}
    return bool(env["CORTEX_API_KEY"] or env["PEGASUS_CERT_PATH"]
                or (env["CORTEX_CLIENT_ID"] and env["CORTEX_CLIENT_SECRET"]))


@functools.cache
def deepeval_llm() -> CortexLLM:
    """Return one shared CortexLLM per process."""
    return CortexLLM()


def pegasus_llm() -> Any:
    """Return the LLM object Pegasus metrics take (`llm=`), using the cortex_v2 or cortex_api adapter.
    Raises JudgeConfigError when api_key mode has no usable credentials."""
    model = os.environ.get("PEGASUS_CORTEX_MODEL") or os.environ.get("CORTEX_MODEL") or "gemini-2.5-flash"
    if auth_mode() == "devkit":
        return _pegasus_model(adapter="cortex_v2", model_name=model, auth_mode="devkit",
                              cortex_env=os.environ.get("CORTEX_ENV", "").strip() or "prd")
    if not pegasus_can_authenticate():
        raise JudgeConfigError("Pegasus needs CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET in env/.env "
                               "(or use CORTEX_AUTH=devkit)")
    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    return _pegasus_model(
        adapter="cortex_api",
        # the client-id/secret gateway wants the provider prefix
        model_name=model if api_key or "/" in model else f"vertex_ai/{model}",
        base_url=os.environ.get("CORTEX_BASE_URL") or require("CORTEX_HOST", JudgeConfigError),
        api_key=api_key,
        client_id=os.environ.get("CORTEX_CLIENT_ID", "").strip(),
        client_secret=os.environ.get("CORTEX_CLIENT_SECRET", "").strip(),
        cert_path=os.environ.get("PEGASUS_CERT_PATH", "").strip(),
    )


@functools.lru_cache(maxsize=2)
def _pegasus_model(**settings: str) -> Any:
    """Build (once per process) a Pegasus model with get_model(), leaving out unset settings."""
    from pegasus.utils.adapters import get_model  # internal package: only imported when Pegasus runs

    kwargs: dict[str, Any] = {"model_type": "llm", "ssl_verify": tls.verify_enabled()}
    kwargs.update({k: v for k, v in settings.items() if v})
    try:
        return get_model(**kwargs)
    except TypeError:  # older Pegasus versions don't accept ssl_verify
        kwargs.pop("ssl_verify")
        return get_model(**kwargs)


def _to_schema(text: str, schema: Any) -> Any:
    """Parse the model's JSON into DeepEval's schema; raises TypeError so DeepEval retries without one."""
    try:
        return schema(**json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Schemas with a single `response` field just want the text.
    if set(getattr(schema, "model_fields", {})) == {"response"}:
        return schema(response=text)
    # A TypeError makes DeepEval retry without a schema and parse the JSON itself.
    raise TypeError(f"CORTEX output does not match {schema.__name__}")
