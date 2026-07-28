"""
Knowledge Agent helpers: deterministic checks + judge prep.

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


def to_pegasus_row(
    case: dict[str, Any],
    response: AgentResponse,
    *,
    question: str = "",
) -> dict[str, Any]:
    """
    Map KA case/response into Pegasus RAG column names.

    Pegasus expects: question, answer, retrieved_contexts [, reference_answer]
    """
    expected = case.get("expected") or {}
    meta = response.metadata or {}

    q = (
        question
        or str((case.get("input") or {}).get("question") or "")
        or str(meta.get("question") or "")
    )
    answer = response.answer or ""
    reference = (
        expected.get("expected_answer")
        or expected.get("answer")
        or meta.get("expected_answer")
        or ""
    )

    contexts: list[str] = []
    if isinstance(response.context, list):
        contexts.extend(str(c) for c in response.context if str(c).strip())
    anchor = str(meta.get("anchor_page_content") or "").strip()
    if anchor and anchor not in contexts:
        contexts.append(anchor)
    existing = meta.get("retrieved_contexts")
    if isinstance(existing, list):
        for c in existing:
            text = str(c).strip()
            if text and text not in contexts:
                contexts.append(text)

    return {
        "question": q,
        "answer": answer,
        "retrieved_contexts": contexts,
        "reference_answer": str(reference) if reference else "",
    }


def prepare_for_judges(
    case: dict[str, Any],
    response: AgentResponse,
) -> AgentResponse:
    """
    Attach SME golden + Pegasus-standard fields so both backends can score.

    DeepEval path: expected_answer / existing *_source fields
    Pegasus path: question, answer, retrieved_contexts, reference_answer
    """
    question = str((case.get("input") or {}).get("question") or "")
    row = to_pegasus_row(case, response, question=question)

    meta = dict(response.metadata or {})
    if row["reference_answer"]:
        meta["expected_answer"] = row["reference_answer"]
        meta["reference_answer"] = row["reference_answer"]

    articles = (case.get("expected") or {}).get("expected_source_articles")
    if articles:
        meta["expected_source_articles"] = articles

    # Pegasus RAG columns (also useful as shared retrieval_context for DeepEval).
    meta["question"] = row["question"]
    meta["retrieved_contexts"] = row["retrieved_contexts"]

    return response.model_copy(
        update={
            "answer": row["answer"] or response.answer,
            "context": row["retrieved_contexts"],
            "metadata": meta,
        }
    )
