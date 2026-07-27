"""
HTTP client for the internal CORTEX LLM gateway.

Aligned with working factfind/ai-evals/core/{eval_config,cortex_llm}.py:
  - HTTPS + unverified SSL (corporate proxy)
  - POST {CORTEX_HOST}/chat/completions
  - header x-lbg-origin-client-id: CORTEX_CLIENT_ID
  - model vertex_ai/gemini-2.5-pro (project-bound)
"""

from __future__ import annotations

import json
import os
import ssl

from src.core.exceptions import CortexClientError
from src.core.network import post_json

_INSECURE_TLS_APPLIED = False


def _apply_insecure_tls() -> None:
    """Match working eval_config SSL monkeypatch for DeepEval/urllib3 too."""
    global _INSECURE_TLS_APPLIED
    if _INSECURE_TLS_APPLIED:
        return
    _INSECURE_TLS_APPLIED = True

    def _unverified_context(*_args, **_kwargs):
        ctx = ssl._create_unverified_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _unverified_context  # type: ignore[assignment]
    os.environ.setdefault("OPENAI_API_KEY", "sk-dummy-not-used")
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001
        pass


def _host_and_chat_path(cortex_host: str) -> tuple[str, str, str]:
    """
    Same as working eval_config:
      CORTEX_HOST=https://host/.../v1/  →  host + /.../v1/chat/completions
    """
    raw = (cortex_host or "").strip().rstrip("/")
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
    else:
        scheme, rest = "https", raw
    scheme = scheme.lower()
    host, _, path_rest = rest.partition("/")
    if path_rest:
        path = f"/{path_rest.rstrip('/')}/chat/completions"
    else:
        path = "/chat/completions"
    return scheme, host, path


def _strip_markdown_fence(content: str) -> str:
    # Gemini 2.5 Pro sometimes wraps JSON scoring output in ```json ... ```
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


class CortexClient:
    """Config from configs/cortex.yaml + .env (same shape as working eval_config)."""

    def __init__(self, config: dict):
        self.base_url: str = str(config["base_url"]).rstrip("/")
        self.model: str = str(config.get("model") or "vertex_ai/gemini-2.5-pro")
        self.temperature: float = float(config.get("temperature", 0.0))
        self.timeout_s: float = float(config.get("timeout_s", 30))
        self.verify_tls: bool = bool(config.get("verify_tls", True))
        self.retries: int = int(config.get("retries", 2))

        if not self.verify_tls:
            _apply_insecure_tls()

        # Working repo: only x-lbg-origin-client-id
        client_id = os.environ.get("CORTEX_CLIENT_ID", "").strip()
        if not client_id:
            # also allow expanded header from yaml headers_from_env already applied upstream
            for env_var in (config.get("headers_from_env") or {}).values():
                client_id = os.environ.get(str(env_var), "").strip()
                if client_id:
                    break
        if not client_id:
            raise CortexClientError(
                "CORTEX_CLIENT_ID is missing/empty — copy it exactly from "
                "working factfind env/.env.factfind.api into repo-root .env"
            )

        self.headers = {
            "content-type": "application/json",
            "x-lbg-origin-client-id": client_id,
            **dict(config.get("extra_headers") or {}),
        }
        self.scheme, self.host, self.path = _host_and_chat_path(self.base_url)

    def chat(self, messages: list[dict]) -> str:
        """POST chat/completions — same as working _cortex_chat()."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        try:
            data = post_json(
                self.host,
                self.path,
                payload,
                self.headers,
                scheme=self.scheme,
                verify_tls=self.verify_tls,
                timeout_s=self.timeout_s,
                retries=self.retries,
            )
            content = data["choices"][0]["message"]["content"]
            return _strip_markdown_fence(str(content))
        except Exception as exc:  # noqa: BLE001
            hint = ""
            err = str(exc)
            if "401" in err or "No_matching_project" in err:
                hint = (
                    " Hint: use CORTEX_MODEL=vertex_ai/gemini-2.5-pro and the exact "
                    "CORTEX_CLIENT_ID from working .env.factfind.api "
                    f"(model now={self.model!r})."
                )
            raise CortexClientError(
                f"CORTEX call to {self.scheme}://{self.host}{self.path} failed: {exc}.{hint}"
            ) from exc

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])
