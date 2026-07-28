"""
Knowledge Agent helpers: attach SME golden answer for suite judges.

Shared judge scoring stays in src.runners.evaluate.evaluate(...).
"""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse


def prepare_for_judges(
    case: dict[str, Any],
    response: AgentResponse,
) -> AgentResponse:
    """
    Copy expected.expected_answer (or legacy expected.answer) onto
    response.metadata so correctness judges can resolve expected_source.
    """
    expected = case.get("expected") or {}
    golden = expected.get("expected_answer") or expected.get("answer")
    articles = expected.get("expected_source_articles")

    if not golden and not articles:
        return response

    meta = dict(response.metadata or {})
    if golden:
        meta["expected_answer"] = str(golden)
    if articles:
        meta["expected_source_articles"] = articles

    return response.model_copy(update={"metadata": meta})
