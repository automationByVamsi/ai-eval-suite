"""Shared sanity helpers for VERDICT adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers import adk_parser
from src.runners.evaluate import CheckResult, load_trace


def response_from_trace(trace_path: Path, case: dict[str, Any]) -> AgentResponse:
    wrapped = load_trace(trace_path, case)
    raw = wrapped.get("raw_output") or {}
    return AgentResponse(
        answer=adk_parser.extract_answer(raw),
        raw_output=raw if isinstance(raw, dict) else {},
        context=adk_parser.extract_context(raw),
        events=adk_parser.extract_events(raw),
        session_id=adk_parser.extract_session_id(raw),
        latency_ms=adk_parser.extract_latency_ms(raw),
    )


def answer_and_keyword_checks(
    case: dict[str, Any],
    response: AgentResponse,
) -> list[CheckResult]:
    results = [
        CheckResult(
            name="answer_non_empty",
            passed=bool((response.answer or "").strip()),
            reason="" if response.answer else "empty agent answer",
        )
    ]
    answer_l = (response.answer or "").lower()
    for kw in case.get("expected", {}).get("keywords") or []:
        ok = str(kw).lower() in answer_l
        results.append(
            CheckResult(
                name=f"keyword:{kw}",
                passed=ok,
                reason="" if ok else f"expected keyword {kw!r} not found",
            )
        )
    return results
