"""
Knowledge Agent helpers: deterministic checks + SME golden for judges.

Shared judge scoring stays in src.runners.evaluate.evaluate(...).
"""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers.knowledge_agent import extract
from src.runners.evaluate import CheckResult
from tests.support.sanity import check


def run_deterministic(
    case: dict[str, Any],
    raw: dict[str, Any],
    question: str,
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Named structural checks + a few view fields for the dashboard."""
    view = extract(raw)
    expected = case.get("expected") or {}
    answer_l = view.answer.lower()

    checks: list[CheckResult] = [
        check("answer_non_empty", bool(view.answer.strip()), "empty agent answer"),
        check(
            "rewritten_query_present",
            bool(view.rewritten_query.strip()),
            "missing rewritten_query",
        ),
        check(
            "anchor_page_id_present",
            bool(view.anchor_page_id.strip()),
            "missing anchor_page_id",
        ),
        check("question_present", bool(question.strip()), "case input.question required"),
    ]

    for kw in expected.get("keywords") or []:
        ok = str(kw).lower() in answer_l
        checks.append(check(f"keyword:{kw}", ok, f"keyword {kw!r} not found in answer"))

    want_anchor = expected.get("expected_anchor_page_id")
    if want_anchor:
        checks.append(
            check(
                "anchor_page_id",
                view.anchor_page_id == str(want_anchor),
                f"anchor_page_id={view.anchor_page_id!r}, expected {want_anchor!r}",
            )
        )

    fields = {
        "rewritten_query": view.rewritten_query,
        "anchor_page_id": view.anchor_page_id,
        "business_area": view.business_area,
        "decision": view.decision,
    }
    return checks, fields


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
