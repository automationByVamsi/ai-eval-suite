"""Knowledge Agent — stage1 / stage2 contracts for VERDICT."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers.knowledge_agent.stage1 import parse as parse_stage1
from src.parsers.knowledge_agent.stage2 import parse as parse_stage2
from src.runners.evaluate import CheckResult, evaluate, load_trace
from src.verdict import obs
from src.verdict.models import CheckObservation
from src.verdict.registry import AgentPack, register
from tests.knowledge_agent import stage1_contract, stage2_contract


def prepare_stage1(
    response_path: str | Path,
    case: dict[str, Any],
) -> tuple[list[CheckResult], AgentResponse]:
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
    return det, response


def prepare_stage2(
    response_path: str | Path,
    case: dict[str, Any],
) -> tuple[list[CheckResult], AgentResponse]:
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
    return det, response


def _eval_stage1(
    agent: str,
    case: dict[str, Any],
    trace_path: Path,
    run_judges: bool,
) -> list[CheckObservation]:
    det, response = prepare_stage1(trace_path, case)
    checks = obs.from_deterministic(det)
    if run_judges:
        judges = evaluate(agent, stage1_contract.STAGE, case, response, publish=False)
        checks.extend(obs.from_judges(judges.judges))
    return checks


def _eval_stage2(
    agent: str,
    case: dict[str, Any],
    trace_path: Path,
    run_judges: bool,
) -> list[CheckObservation]:
    det, response = prepare_stage2(trace_path, case)
    checks = obs.from_deterministic(det)
    if run_judges:
        judges = evaluate(agent, stage2_contract.STAGE, case, response, publish=False)
        checks.extend(obs.from_judges(judges.judges))
    return checks


register(
    AgentPack(
        agent="knowledge_agent",
        default_suite="sanity",
        packs={
            stage1_contract.STAGE: _eval_stage1,
            stage2_contract.STAGE: _eval_stage2,
        },
        sim_fail={
            stage1_contract.STAGE: frozenset({"result_count_positive", "query_optimization"}),
            stage2_contract.STAGE: frozenset({"anchor_accuracy", "anchor_relevance"}),
        },
    )
)
