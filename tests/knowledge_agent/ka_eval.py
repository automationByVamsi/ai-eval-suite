"""
Knowledge Agent–only helpers: stage parse + deterministic contracts.

Shared judge scoring stays in src.runners.evaluate.evaluate(...).
"""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers.knowledge_agent.stage1 import Stage1Parsed
from src.parsers.knowledge_agent.stage1 import parse as parse_stage1
from src.runners.evaluate import CheckResult, load_trace
from tests.knowledge_agent import stage1_contract


def prepare_stage1(
    response_path: str,
    case: dict[str, Any],
) -> tuple[Stage1Parsed, list[CheckResult], AgentResponse]:
    """
    Load trace → parse stage1 → run deterministic contract →
    AgentResponse ready for evaluate(..., suite=...).
    """
    trace = load_trace(response_path, case)
    parsed = parse_stage1(trace)
    det = [
        CheckResult(name=r.name, passed=r.passed, reason=r.reason or "")
        for r in stage1_contract.run_deterministic(parsed)
    ]
    response = stage1_response_for_judges(parsed, case)
    return parsed, det, response


def stage1_response_for_judges(
    parsed: Stage1Parsed,
    case: dict[str, Any] | None = None,
) -> AgentResponse:
    """Map stage1 fields into metadata so catalog input_source/actual_source resolve."""
    question = (case or {}).get("input", {}).get("question") or parsed.question or ""
    return AgentResponse(
        answer=parsed.answer or "",
        context=list(parsed.context or []),
        events=list(parsed.events or []),
        metadata={
            "question": question,
            "rewritten_query": parsed.rewritten_query or "",
            "business_area": parsed.business_area or "",
            "artifact_id": parsed.artifact_id or "",
        },
        session_id=parsed.session_id,
        latency_ms=parsed.latency_ms,
    )
