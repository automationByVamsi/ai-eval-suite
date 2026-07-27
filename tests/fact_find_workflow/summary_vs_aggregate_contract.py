"""
Summary vs aggregate contract — Summary quality vs aggregated payload.

Layer 1 deterministic (identity + high-risk fields).
Layer 2 LLM judges (groundedness, fidelity, honesty).

On path=invalid_complaint, only the invalid-path check runs.
"""

from src.models.evaluation_result import DeterministicCheckResult
from src.parsers.fact_find_workflow.summary_vs_aggregate import SummaryVsAggregateParsed

STAGE = "summary_vs_aggregate"

DETERMINISTIC_CHECKS_SUCCESS = [
    "aggregated_payload_loaded",
    "summary_sections_present",
    "identifier_fidelity",
    "customer_profile_grounded",
    "support_needs_coverage",
    "complaint_account_marked",
    "missing_trusted_parties_honest",
    "related_parties_grounded",
]

DETERMINISTIC_CHECKS_INVALID = [
    "no_summary_on_invalid_path",
]


def assert_aggregated_payload_loaded(parsed: SummaryVsAggregateParsed) -> None:
    assert parsed.expected_facts, "expected_facts empty — aggregated_payload_path missing or unloadable"
    assert parsed.context, "retrieval context empty — cannot judge groundedness"


def assert_summary_sections_present(parsed: SummaryVsAggregateParsed) -> None:
    missing = []
    if not parsed.has_customer_profile_section:
        missing.append("Customer Profile")
    if not parsed.has_support_needs_section and parsed.support_needs_total > 0:
        missing.append("Support Needs")
    if not parsed.has_account_holdings_section:
        missing.append("Account Holdings")
    if not parsed.has_contact_notes_section and (parsed.expected_facts.get("contact_note_count") or 0) > 0:
        missing.append("Contact Notes")
    assert not missing, f"Summary missing sections: {missing}"


def assert_identifier_fidelity(parsed: SummaryVsAggregateParsed) -> None:
    missing = []
    if not parsed.mentioned_complaint_ref:
        missing.append("complaint_ref")
    if not parsed.mentioned_party_id:
        missing.append("party_id")
    if not parsed.mentioned_account_number:
        missing.append("account_number")
    assert not missing, f"Critical identifiers missing from summary: {missing}"


def assert_customer_profile_grounded(parsed: SummaryVsAggregateParsed) -> None:
    facts = parsed.expected_facts
    missing = []
    if facts.get("customer_name_tokens") and not parsed.mentioned_customer_name:
        missing.append("customer_name")
    if facts.get("date_of_birth") and not parsed.mentioned_dob:
        missing.append("date_of_birth")
    if facts.get("postcode") and not parsed.mentioned_postcode:
        missing.append("postcode")
    if facts.get("marital_status") and not parsed.mentioned_marital_status:
        missing.append("marital_status")
    assert not missing, f"Customer profile fields not grounded: {missing}"


def assert_support_needs_coverage(parsed: SummaryVsAggregateParsed) -> None:
    total = parsed.support_needs_total
    if total == 0:
        return
    # Require at least 80% of support-need descriptions (vulnerability-critical).
    ratio = parsed.support_needs_hit_count / total
    assert ratio >= 0.8, (
        f"Support needs coverage {parsed.support_needs_hit_count}/{total} "
        f"({ratio:.0%}); expected ≥ 80%"
    )


def assert_complaint_account_marked(parsed: SummaryVsAggregateParsed) -> None:
    if not parsed.expected_facts.get("account_number_full"):
        return
    assert parsed.marks_complaint_associated_account, (
        "Complaint-associated account not called out in Account Holdings"
    )


def assert_missing_trusted_parties_honest(parsed: SummaryVsAggregateParsed) -> None:
    facts = parsed.expected_facts
    if not (facts.get("trusted_parties_failed") or facts.get("trusted_parties_empty")):
        return
    assert parsed.mentions_no_trusted_party or not parsed.invents_trusted_party, (
        "Trusted Parties API failed/empty but summary invents trusted-party data"
    )
    assert not parsed.invents_trusted_party, (
        "Summary appears to invent Trusted Party details when ground truth has none/error"
    )


def assert_related_parties_grounded(parsed: SummaryVsAggregateParsed) -> None:
    related_ids = parsed.expected_facts.get("related_party_ids") or []
    if not related_ids:
        return
    assert parsed.has_related_parties_section, "Related Parties section missing"
    assert parsed.mentioned_related_party_id, (
        f"None of related party IDs {related_ids} found in summary"
    )


def assert_no_summary_on_invalid_path(parsed: SummaryVsAggregateParsed) -> None:
    assert parsed.path == "invalid_complaint" or parsed.validation_failed, (
        "Invalid-path check invoked without invalid markers"
    )
    assert not parsed.has_customer_profile_section, (
        "Invalid complaint path unexpectedly includes Customer Profile"
    )


def run_deterministic(parsed: SummaryVsAggregateParsed, expected: dict | None = None) -> list[DeterministicCheckResult]:
    expected = expected or {}
    path = expected.get("path") or parsed.path
    if path == "invalid_complaint":
        check_names = DETERMINISTIC_CHECKS_INVALID
        runners = {"no_summary_on_invalid_path": assert_no_summary_on_invalid_path}
    else:
        check_names = DETERMINISTIC_CHECKS_SUCCESS
        runners = {
            "aggregated_payload_loaded": assert_aggregated_payload_loaded,
            "summary_sections_present": assert_summary_sections_present,
            "identifier_fidelity": assert_identifier_fidelity,
            "customer_profile_grounded": assert_customer_profile_grounded,
            "support_needs_coverage": assert_support_needs_coverage,
            "complaint_account_marked": assert_complaint_account_marked,
            "missing_trusted_parties_honest": assert_missing_trusted_parties_honest,
            "related_parties_grounded": assert_related_parties_grounded,
        }

    results = []
    for name in check_names:
        try:
            runners[name](parsed)
            results.append(DeterministicCheckResult(name=name, passed=True))
        except AssertionError as exc:
            results.append(DeterministicCheckResult(name=name, passed=False, reason=str(exc)))
    return results


# Mirrors configs/evaluations/fact_find_workflow/summary_vs_aggregate.yaml
JUDGE_METRICS = [
    "faithfulness",
    "relevance",
    "summarization",
    "task_completion",
    "support_needs_fidelity",
    "profile_accuracy",
    "missing_data_honesty",
    "complaint_account_association",
]

JUDGE_METRICS_INVALID: list[str] = []
