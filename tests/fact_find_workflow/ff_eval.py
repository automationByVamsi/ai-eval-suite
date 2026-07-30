"""
Fact Find helpers: deterministic checks only.

Judge packaging: parsers.prepare_response → src.eval.prepare_sample.
"""

from __future__ import annotations

from typing import Any

from src.parsers.fact_find_workflow import extract
from src.runners.evaluate import CheckResult
from tests.support.sanity import check


def run_deterministic(
    case: dict[str, Any],
    raw: dict[str, Any],
    complaint_ref: str,
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Named path checks + a few view fields for the dashboard."""
    view = extract(raw, complaint_ref=complaint_ref)
    expected = case.get("expected") or {}
    path = expected.get("path")
    answer_l = view.answer.lower()

    checks: list[CheckResult] = [
        check("answer_non_empty", bool(view.answer.strip()), "empty agent answer"),
    ]

    for kw in expected.get("keywords") or []:
        ok = str(kw).lower() in answer_l
        checks.append(check(f"keyword:{kw}", ok, f"keyword {kw!r} not found in answer"))

    if path == "success":
        checks.append(
            check("looks_like_summary", view.looks_like_summary, "expected FactFind summary")
        )
        checks.append(
            check(
                "not_invalid_complaint",
                not view.is_invalid_message,
                "unexpected InvalidComplaintId",
            )
        )
        checks.append(
            check(
                "validation_ok",
                not view.validation_failed,
                "validation_failed on success path",
            )
        )
        ref_ok = complaint_ref in view.answer or view.complaint_ref == complaint_ref
        checks.append(
            check("complaint_ref_present", ref_ok, f"complaint_ref {complaint_ref!r} missing")
        )

        want_party = expected.get("party_id")
        if want_party and view.party_id:
            checks.append(
                check(
                    "party_id",
                    view.party_id == str(want_party),
                    f"party_id={view.party_id!r}, expected {want_party!r}",
                )
            )
        if view.tool_names:
            checks.append(
                check("tools_called", len(view.tool_names) >= 1, "expected at least one tool")
            )

    if path == "invalid_complaint":
        checks.append(
            check(
                "invalid_complaint_signal",
                view.validation_failed or view.is_invalid_message,
                "expected invalid-complaint signals",
            )
        )
        checks.append(
            check(
                "not_summary",
                not view.looks_like_summary,
                "invalid path should not look like a summary",
            )
        )

    fields = {
        "path": path,
        "complaint_ref": view.complaint_ref or complaint_ref,
        "party_id": view.party_id,
        "validation_failed": view.validation_failed,
        "looks_like_summary": view.looks_like_summary,
        "tool_names": list(view.tool_names),
    }
    return checks, fields
