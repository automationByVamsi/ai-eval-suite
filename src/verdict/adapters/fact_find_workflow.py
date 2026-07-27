"""Fact Find Workflow — sanity keywords (+ optional suite judges) for VERDICT."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers import adk_parser
from src.runners.evaluate import CheckResult, evaluate, load_trace
from src.verdict import obs
from src.verdict.models import CheckObservation
from src.verdict.registry import AgentPack, register
from tests.fact_find_workflow.ff_eval import prepare_for_judges, suite_for_case

PACK = "sanity"


def _response_from_trace(trace_path: Path, case: dict[str, Any]) -> AgentResponse:
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


def _deterministic(case: dict[str, Any], response: AgentResponse) -> list[CheckResult]:
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


def _eval_sanity(
    agent: str,
    case: dict[str, Any],
    trace_path: Path,
    run_judges: bool,
) -> list[CheckObservation]:
    response = _response_from_trace(trace_path, case)
    checks = obs.from_deterministic(_deterministic(case, response))
    if run_judges:
        enriched = prepare_for_judges(case, response)
        suite = suite_for_case(case)
        judges = evaluate(agent, suite, case, enriched, publish=False)
        checks.extend(obs.from_judges(judges.judges))
    return checks


register(
    AgentPack(
        agent="fact_find_workflow",
        default_suite="sanity",
        packs={PACK: _eval_sanity},
        sim_fail={PACK: frozenset({"answer_non_empty"})},
    )
)
