"""
Temporary KA stage helpers for VERDICT (until stage1/stage2 are redesigned).

Parse saved traces → deterministic contracts → AgentResponse for optional judges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers.knowledge_agent.stage1 import Stage1Parsed
from src.parsers.knowledge_agent.stage1 import parse as parse_stage1
from src.parsers.knowledge_agent.stage2 import Stage2Parsed
from src.parsers.knowledge_agent.stage2 import parse as parse_stage2
from src.runners.evaluate import CheckResult, load_trace
from tests.knowledge_agent import stage1_contract, stage2_contract


def resolve_trace_path(
    case_id: str,
    *,
    agent: str = "knowledge_agent",
    data_suite: str = "sanity",
    traces_root: str | Path = "outputs/traces",
) -> Path:
    path = Path(traces_root) / agent / data_suite / f"{case_id}.json"
    if path.is_file():
        return path
    raise FileNotFoundError(
        f"No trace at {path}. Run: pytest tests/knowledge_agent/test_sanity.py -v -s"
    )


def prepare_stage1(
    response_path: str,
    case: dict[str, Any],
) -> tuple[Stage1Parsed, list[CheckResult], AgentResponse]:
    trace = load_trace(response_path, case)
    parsed = parse_stage1(trace)
    det = [
        CheckResult(name=r.name, passed=r.passed, reason=r.reason or "")
        for r in stage1_contract.run_deterministic(parsed)
    ]
    question = case.get("input", {}).get("question") or parsed.question or ""
    response = AgentResponse(
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
    return parsed, det, response


def prepare_stage2(
    response_path: str,
    case: dict[str, Any],
) -> tuple[Stage2Parsed, list[CheckResult], AgentResponse]:
    trace = load_trace(response_path, case)
    parsed = parse_stage2(trace)
    det = [
        CheckResult(name=r.name, passed=r.passed, reason=r.reason or "")
        for r in stage2_contract.run_deterministic(
            parsed, expected=case.get("expected") or {}
        )
    ]
    question = case.get("input", {}).get("question") or ""
    response = AgentResponse(
        answer=parsed.anchor_page_content or parsed.answer or "",
        context=list(parsed.context or []),
        events=list(parsed.events or []),
        metadata={
            "question": question,
            "rewritten_query": parsed.rewritten_query or "",
            "anchor_page_id": parsed.anchor_page_id or "",
            "anchor_page_content": parsed.anchor_page_content or "",
        },
        session_id=parsed.session_id,
        latency_ms=parsed.latency_ms,
    )
    return parsed, det, response
