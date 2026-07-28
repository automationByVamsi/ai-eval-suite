"""Minimal CORTEX client used by DeepEval judges."""

from __future__ import annotations

import os
import ssl

from src.core.exceptions import CortexClientError
from src.core.network import post_json

_TLS_PATCHED = False


def _apply_insecure_tls() -> None:
    """Match working setup: disable TLS verification process-wide for judges."""
    global _TLS_PATCHED
    if _TLS_PATCHED:
        return
    _TLS_PATCHED = True

    def _unverified_context(*_args, **_kwargs):
        """Return an SSL context with hostname and cert checks disabled."""
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
    CORTEX_HOST=https://host/.../v1/ -> host + /.../v1/chat/completions
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
    """Remove a surrounding Markdown fence from model output."""
    # Gemini 2.5 Pro sometimes wraps JSON scoring output in ```json ... ```
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


class CortexClient:
    """Thin wrapper around POST /chat/completions."""

    def __init__(self, config: dict):
        """Store CORTEX request settings and resolve auth headers."""
        self.base_url: str = str(config["base_url"]).rstrip("/")
        self.model: str = str(config.get("model") or "vertex_ai/gemini-2.5-pro")
        self.temperature: float = float(config.get("temperature", 0.0))
        self.timeout_s: float = float(config.get("timeout_s", 30))
        self.verify_tls: bool = bool(config.get("verify_tls", True))
        self.retries: int = int(config.get("retries", 2))

        if not self.verify_tls:
            _apply_insecure_tls()

        client_id = os.environ.get("CORTEX_CLIENT_ID", "").strip()
        if not client_id:
            raise CortexClientError(
                "CORTEX_CLIENT_ID is missing/empty in environment."
            )

        self.headers = {
            "content-type": "application/json",
            "x-lbg-origin-client-id": client_id,
            **dict(config.get("extra_headers") or {}),
        }
        self.scheme, self.host, self.path = _host_and_chat_path(self.base_url)

    def chat(self, messages: list[dict]) -> str:
        """POST chat/completions and return plain text."""
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
            raise CortexClientError(
                f"CORTEX call to {self.scheme}://{self.host}{self.path} failed: {exc}"
            ) from exc

    def generate(self, prompt: str) -> str:
        """Send one user prompt to CORTEX and return plain text."""
        return self.chat([{"role": "user", "content": prompt}])
