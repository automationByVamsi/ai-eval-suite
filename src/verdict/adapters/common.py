"""Shared sanity helpers for VERDICT adapters."""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse
from src.runners.evaluate import CheckResult


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
