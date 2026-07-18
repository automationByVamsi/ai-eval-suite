"""
Live HTTP adapter for a real Google ADK agent deployment. Implements the
actual two-step ADK contract - create a session, then POST a message to
/run and get back the raw event stream - rather than a generic "POST some
JSON, get JSON back" placeholder.

config: {base_url, base_path, app_name, user_id, message_field, timeout_s,
         verify_tls, max_retries, headers}
"""

import time
from typing import Any

from src.agents import adk_parser
from src.agents.base_agent import BaseAgent
from src.core.exceptions import AgentInvocationError
from src.core.network import post_json, split_host_path
from src.core.registry import AGENT_REGISTRY
from src.models.agent_response import AgentResponse


@AGENT_REGISTRY.register("adk")
class ADKAgentAdapter(BaseAgent):
    def invoke(self, payload: dict[str, Any]) -> AgentResponse:
        host, base_path = split_host_path(self.config["base_url"] + self.config.get("base_path", ""))
        app_name = self.config["app_name"]
        user_id = self.config["user_id"]
        message = payload.get(self.config.get("message_field", "question"), "")
        headers = self.config.get("headers", {})
        call_kwargs = {
            "verify_tls": self.config.get("verify_tls", True),
            "timeout_s": self.config.get("timeout_s", 30),
            "retries": self.config.get("max_retries", 2),
        }

        start = time.perf_counter()
        try:
            session = post_json(host, f"{base_path}/apps/{app_name}/users/{user_id}/sessions", {}, headers, **call_kwargs)
            session_id = session["id"]

            run_payload = {
                "app_name": app_name,
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {"role": "user", "parts": [{"text": message}]},
            }
            events = post_json(host, f"{base_path}/run", run_payload, headers, **call_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise AgentInvocationError(f"ADK agent call to {host}{base_path} failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000

        raw = {
            "agentOutput": self._extract_final_text(events),
            "sessionId": session_id,
            "latency_ms": latency_ms,
            "raw_events": events,
        }

        return AgentResponse(
            answer=adk_parser.extract_answer(raw),
            raw_output=raw,
            context=adk_parser.extract_context(raw),
            events=adk_parser.extract_events(raw),
            session_id=adk_parser.extract_session_id(raw),
            latency_ms=adk_parser.extract_latency_ms(raw),
        )

    @staticmethod
    def _extract_final_text(events: list[dict]) -> str:
        """
        Best-effort: the last event with non-empty text is treated as the
        agent's final output. TODO(agent-api): verify against real
        fact_find/knowledge_agent output once run live - some workflows wrap
        the answer in prose (e.g. "Success branch reached.\\n\\nAnswer:\\n...")
        which this strips off when present.
        """
        for event in reversed(events):
            parts = event.get("content", {}).get("parts", [])
            text = parts[0].get("text", "") if parts else ""
            if text:
                marker = "Answer:\n"
                return text.split(marker, 1)[1].strip() if marker in text else text.strip()
        return ""
