"""
ADK client — create session, run agent, optionally save the full JSON trace.

Every lab agent uses Google ADK the same way. Only config differs
(base_url, app_name, user_id, message field). No BaseAgent / factory.

    client = AdkClient.from_agent_name("knowledge_agent")
    path, answer = client.get_agent_output("How do I request VPN?", save_dir=...)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents import adk_parser
from src.core.config import get_agent_config
from src.core.exceptions import AgentInvocationError
from src.core.network import post_json, split_host_path
from src.models.agent_response import AgentResponse


class AdkClient:
    """Thin HTTP client for one ADK app (config from agents.yaml + .env)."""

    def __init__(self, config: dict[str, Any], *, agent_name: str = ""):
        self.agent_name = agent_name
        self.base_url: str = str(config["base_url"]).rstrip("/")
        self.base_path: str = str(config.get("base_path") or "")
        self.app_name: str = str(config["app_name"])
        self.user_id: str = str(config.get("user_id") or "eval_user")
        self.message_field: str = str(config.get("message_field") or "question")
        self.message_template: str | None = config.get("message_template")
        self.timeout_s: float = float(config.get("timeout_s", 30))
        self.verify_tls: bool = bool(config.get("verify_tls", True))
        self.max_retries: int = int(config.get("max_retries", 2))
        self.headers: dict[str, str] = dict(config.get("headers") or {})
        self.metrics_profile: str = str(
            config.get("metrics_profile") or agent_name or self.app_name
        )

    @classmethod
    def from_agent_name(
        cls,
        agent_name: str,
        agents_path: str | Path = "configs/agents.yaml",
    ) -> AdkClient:
        return cls(get_agent_config(agent_name, path=agents_path), agent_name=agent_name)

    def _host_and_base(self) -> tuple[str, str]:
        return split_host_path(self.base_url + self.base_path)

    def _call_kwargs(self) -> dict[str, Any]:
        return {
            "verify_tls": self.verify_tls,
            "timeout_s": self.timeout_s,
            "retries": self.max_retries,
        }

    def create_session(self) -> str:
        """Step 1 — create ADK session; return session_id."""
        host, base_path = self._host_and_base()
        path = f"{base_path}/apps/{self.app_name}/users/{self.user_id}/sessions"
        try:
            session = post_json(host, path, {}, self.headers, **self._call_kwargs())
        except Exception as exc:  # noqa: BLE001
            raise AgentInvocationError(
                f"ADK create_session failed for {self.app_name}: {exc}"
            ) from exc
        session_id = session.get("id")
        if not session_id:
            raise AgentInvocationError(f"ADK session response missing id: {session!r}")
        return str(session_id)

    def run(self, session_id: str, user_text: str) -> tuple[list[dict[str, Any]], str]:
        """Step 2 — POST /run; return (raw_events, final_answer_text)."""
        host, base_path = self._host_and_base()
        path = f"{base_path}/run"
        payload = {
            "app_name": self.app_name,
            "user_id": self.user_id,
            "session_id": session_id,
            "new_message": {"role": "user", "parts": [{"text": user_text}]},
        }
        try:
            events = post_json(host, path, payload, self.headers, **self._call_kwargs())
        except Exception as exc:  # noqa: BLE001
            raise AgentInvocationError(
                f"ADK /run failed for {self.app_name}: {exc}"
            ) from exc
        if not isinstance(events, list):
            raise AgentInvocationError(
                f"ADK /run expected a list of events, got {type(events).__name__}"
            )
        return events, extract_final_text(events)

    def build_user_text(self, payload: dict[str, Any]) -> str:
        """Turn test-case input into the ADK user message string."""
        value = payload.get(self.message_field, "")
        if value is None:
            value = ""
        text = str(value)
        if self.message_template:
            return self.message_template.format(value=text, **payload)
        return text

    def save_output(
        self,
        *,
        save_dir: Path,
        case_id: str,
        session_id: str,
        events: list[dict[str, Any]],
        final_text: str,
        latency_ms: float,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Persist the full agent JSON (events + answer) for offline eval."""
        save_dir.mkdir(parents=True, exist_ok=True)
        raw = {
            "agentOutput": final_text,
            "sessionId": session_id,
            "latency_ms": latency_ms,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "app_name": self.app_name,
            "raw_events": events,
        }
        if extra:
            raw.update(extra)
        path = save_dir / f"{case_id}.json"
        path.write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")
        return path

    def get_agent_output(
        self,
        user_text: str,
        *,
        case_id: str = "run",
        save_dir: Path | None = None,
        retries: int | None = None,
        delay_s: float = 2.0,
    ) -> tuple[AgentResponse, Path | None]:
        """
        Session → run → optional save. Retries the whole sequence on failure.
        Returns (AgentResponse, saved_path_or_None).
        """
        attempts = (retries if retries is not None else self.max_retries) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            start = time.perf_counter()
            try:
                session_id = self.create_session()
                events, final_text = self.run(session_id, user_text)
                latency_ms = (time.perf_counter() - start) * 1000
                saved: Path | None = None
                if save_dir is not None:
                    saved = self.save_output(
                        save_dir=save_dir,
                        case_id=case_id,
                        session_id=session_id,
                        events=events,
                        final_text=final_text,
                        latency_ms=latency_ms,
                    )
                raw = {
                    "agentOutput": final_text,
                    "sessionId": session_id,
                    "latency_ms": latency_ms,
                    "raw_events": events,
                }
                return _response_from_raw(raw), saved
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(delay_s)
        raise AgentInvocationError(
            f"ADK call for {self.app_name} failed after {attempts} attempt(s): {last_error}"
        ) from last_error


def extract_final_text(events: list[dict[str, Any]]) -> str:
    """
    Best-effort final answer from ADK events.

    Prefers the last model text part that is not an internal "thought".
    Strips a trailing "Answer:\\n..." wrapper when present (some workflows).
    """
    final_text = ""
    for event in events:
        content = event.get("content") or {}
        if content.get("role") and content.get("role") != "model":
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if "thought" in part:
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                final_text = text.strip()

    if not final_text:
        # Fallback: last non-empty text anywhere (older traces / odd shapes)
        for event in reversed(events):
            parts = (event.get("content") or {}).get("parts") or []
            if not parts:
                continue
            text = parts[0].get("text", "") if isinstance(parts[0], dict) else ""
            if text:
                final_text = text.strip()
                break

    marker = "Answer:\n"
    if marker in final_text:
        return final_text.split(marker, 1)[1].strip()
    return final_text


def _response_from_raw(raw: dict[str, Any]) -> AgentResponse:
    return AgentResponse(
        answer=adk_parser.extract_answer(raw),
        raw_output=raw,
        context=adk_parser.extract_context(raw),
        events=adk_parser.extract_events(raw),
        session_id=adk_parser.extract_session_id(raw),
        latency_ms=adk_parser.extract_latency_ms(raw),
    )


def invoke_agent(
    agent_name: str,
    payload: dict[str, Any],
    *,
    save_dir: Path | None = None,
    agents_path: str | Path = "configs/agents.yaml",
) -> AgentResponse:
    """Live ADK call for one input; optionally save under save_dir."""
    case_id = str(payload.get("_test_case_id") or "run")
    client = AdkClient.from_agent_name(agent_name, agents_path=agents_path)
    user_text = client.build_user_text(payload)
    response, _saved = client.get_agent_output(
        user_text,
        case_id=case_id,
        save_dir=save_dir,
    )
    return response
