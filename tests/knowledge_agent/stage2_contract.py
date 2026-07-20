"""
Stage 2 contract — Anchor Node Identification.

Layer 1: deterministic asserts.
Layer 2: judge metric names (YAML + criteria hold the how).
Golden: optional expected_anchor_page_id accuracy when labelled.
"""

from typing import Any, Optional

from src.models.evaluation_result import DeterministicCheckResult
from src.parsers.knowledge_agent.stage2 import Stage2Parsed

STAGE = "stage2_anchor_node"

# Default selection path when expected.anchor_selection_method is absent
DEFAULT_SELECTION_METHOD = "baseline"

DETERMINISTIC_CHECKS = [
    "anchor_selected",
    "anchor_id_valid",
    "anchor_belongs_to_candidates",
    "workflow_completed",
    "selection_path_correct",
]


def assert_anchor_selected(parsed: Stage2Parsed) -> None:
    """#1 Session state contains a non-empty anchor_page_id."""
    assert parsed.anchor_selected and parsed.anchor_page_id, (
        "anchor_page_id is missing or empty in session state"
    )


def assert_anchor_id_valid(parsed: Stage2Parsed) -> None:
    """#2 Anchor ID is a valid KB page identifier (numeric)."""
    assert parsed.anchor_id_valid, (
        f"anchor_page_id={parsed.anchor_page_id!r} is not a valid KB page id"
    )


def assert_anchor_belongs_to_candidates(parsed: Stage2Parsed) -> None:
    """#3 anchor_page_id exists among Stage 1 search candidates (from trace context)."""
    assert parsed.candidate_page_ids, (
        "No candidate page ids found in trace context to validate membership "
        "(offline check; MCP lookup not used)"
    )
    assert parsed.anchor_in_candidates, (
        f"anchor_page_id={parsed.anchor_page_id} not in candidates {parsed.candidate_page_ids}"
    )


def assert_workflow_completed(parsed: Stage2Parsed) -> None:
    """#4 Anchor workflow event completed without errors."""
    assert parsed.workflow_completed, (
        parsed.workflow_error or "Anchor workflow did not complete successfully"
    )


def assert_selection_path_correct(
    parsed: Stage2Parsed,
    *,
    expected_method: Optional[str] = None,
) -> None:
    """#5 Executed selection path matches expected method (default: baseline)."""
    expected = (expected_method or DEFAULT_SELECTION_METHOD).strip().lower()
    path = (parsed.selection_path or "").lower()
    method = (parsed.selection_method or "").lower()
    ok = expected in path or expected in method or f"anchor_{expected}" in path
    assert ok, (
        f"selection path/method mismatch: expected {expected!r}, "
        f"got path={parsed.selection_path!r} method={parsed.selection_method!r}"
    )


def assert_anchor_accuracy(parsed: Stage2Parsed, expected_anchor_page_id: str) -> None:
    """Golden diagnostic: selected anchor matches labelled expected_anchor_page_id."""
    assert parsed.anchor_page_id == str(expected_anchor_page_id).strip(), (
        f"Anchor Accuracy failed: got {parsed.anchor_page_id!r}, "
        f"expected {expected_anchor_page_id!r}"
    )


def run_deterministic(
    parsed: Stage2Parsed,
    expected: Optional[dict[str, Any]] = None,
) -> list[DeterministicCheckResult]:
    expected = expected or {}
    expected_method = expected.get("anchor_selection_method")

    runners = {
        "anchor_selected": lambda: assert_anchor_selected(parsed),
        "anchor_id_valid": lambda: assert_anchor_id_valid(parsed),
        "anchor_belongs_to_candidates": lambda: assert_anchor_belongs_to_candidates(parsed),
        "workflow_completed": lambda: assert_workflow_completed(parsed),
        "selection_path_correct": lambda: assert_selection_path_correct(
            parsed, expected_method=expected_method
        ),
    }

    results: list[DeterministicCheckResult] = []
    for name in DETERMINISTIC_CHECKS:
        try:
            runners[name]()
            results.append(DeterministicCheckResult(name=name, passed=True))
        except AssertionError as exc:
            results.append(DeterministicCheckResult(name=name, passed=False, reason=str(exc)))

    # Optional golden check — only when labelled
    if expected.get("expected_anchor_page_id"):
        name = "anchor_accuracy"
        try:
            assert_anchor_accuracy(parsed, str(expected["expected_anchor_page_id"]))
            results.append(DeterministicCheckResult(name=name, passed=True))
        except AssertionError as exc:
            results.append(DeterministicCheckResult(name=name, passed=False, reason=str(exc)))

    return results


JUDGE_METRICS = [
    "anchor_relevance",
    "anchor_grounding_quality",
]
