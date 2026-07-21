"""
Gate validation contract — Complaint reference validation.

Layer 1: deterministic asserts on ADK state + answer shape.
Layer 2: judge metric names only.
"""

from src.models.evaluation_result import DeterministicCheckResult
from src.parsers.fact_find_workflow.gate_validation import GateValidationParsed, is_valid_complaint_ref

STAGE = "gate_validation"

DETERMINISTIC_CHECKS = [
    "complaint_ref_present",
    "validation_outcome_consistent",
    "state_flags_present",
]


def assert_complaint_ref_present(parsed: GateValidationParsed) -> None:
    assert parsed.complaint_ref and str(parsed.complaint_ref).strip(), (
        "complaint_ref missing from test case / trace"
    )


def assert_validation_outcome_consistent(parsed: GateValidationParsed, expected: dict | None = None) -> None:
    expected = expected or {}
    path = expected.get("path")
    if path == "invalid_complaint":
        assert parsed.validation_failed or parsed.is_invalid_complaint_message, (
            "Expected invalid-complaint path but neither state nor answer indicates rejection"
        )
        assert not parsed.looks_like_summary, (
            "Invalid path unexpectedly produced a Customer FactFind Summary"
        )
        return

    if path == "success":
        assert not parsed.validation_failed, "Success path set complaint_validation_failed"
        assert not parsed.is_invalid_complaint_message, (
            "Success path returned InvalidComplaintId message"
        )
        assert parsed.looks_like_summary or is_valid_complaint_ref(parsed.complaint_ref), (
            "Success path missing summary and complaint_ref is not NC########"
        )
        return

    # Unknown path: answer and state must agree with each other.
    if parsed.validation_failed:
        assert parsed.is_invalid_complaint_message, (
            "complaint_validation_failed=true but answer is not an InvalidComplaintId message"
        )


def assert_state_flags_present(parsed: GateValidationParsed) -> None:
    assert parsed.events, "No ADK raw_events in the captured trace"
    # At least one of the known workflow flags should appear on a real run.
    assert (
        parsed.validation_failed
        or parsed.successful_run is not None
        or parsed.initialized is not None
        or parsed.interaction_count is not None
        or parsed.answer
    ), "Trace has no recognisable fact_find_workflow state flags or answer"


def run_deterministic(parsed: GateValidationParsed, expected: dict | None = None) -> list[DeterministicCheckResult]:
    runners = {
        "complaint_ref_present": lambda p: assert_complaint_ref_present(p),
        "validation_outcome_consistent": lambda p: assert_validation_outcome_consistent(p, expected),
        "state_flags_present": lambda p: assert_state_flags_present(p),
    }
    results = []
    for name in DETERMINISTIC_CHECKS:
        try:
            runners[name](parsed)
            results.append(DeterministicCheckResult(name=name, passed=True))
        except AssertionError as exc:
            results.append(DeterministicCheckResult(name=name, passed=False, reason=str(exc)))
    return results


JUDGE_METRICS = [
    "validation_message_clarity",
    "relevance",
]
