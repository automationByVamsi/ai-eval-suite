"""
HTTP client for the internal CORTEX LLM gateway.

CORTEX is the ONLY LLM every judge metric talks to (see CortexDeepEvalLLM in
cortex_deepeval.py) - no OpenAI key is ever required anywhere in this
framework. Agents never import this client; only metrics/synthesizer do
(dependency injection - see runners/factories.py).

Static-header auth: the client id is passed as a plain header - no OAuth, no
secret. Uses stdlib http.client rather than `requests` (see
src/core/network.py) - proven to work through a TLS-intercepting corporate
proxy where `requests` sometimes isn't.
"""

import os

from src.core.exceptions import CortexClientError
from src.core.network import post_json, split_host_path


class CortexClient:
    """Config is read straight from configs/cortex.yaml - see that file for every key."""

    def __init__(self, config: dict):
        self.base_url: str = config["base_url"].rstrip("/")
        self.path: str = config.get("path", "/v1/generate")
        self.model: str = config["model"]
        self.temperature: float = config.get("temperature", 0.0)
        self.timeout_s: float = config.get("timeout_s", 30)
        self.verify_tls: bool = config.get("verify_tls", True)
        self.retries: int = config.get("retries", 2)

        self.headers = {"Content-Type": "application/json", **config.get("extra_headers", {})}
        for header_name, env_var in config.get("headers_from_env", {}).items():
            self.headers[header_name] = os.environ.get(env_var, "")

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        host, path = split_host_path(self.base_url + self.path)

        try:
            data = post_json(
                host,
                path,
                payload,
                self.headers,
                verify_tls=self.verify_tls,
                timeout_s=self.timeout_s,
                retries=self.retries,
            )
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 - post_json already retried; this is the final failure
            raise CortexClientError(f"CORTEX call to {host}{path} failed: {exc}") from exc
