"""Unit tests for Fact Find parsers (no CORTEX / live ADK required)."""

from pathlib import Path

from src.parsers.fact_find_workflow.aggregated_payload import (
    extract_expected_facts,
    load_aggregated_payload,
    payload_to_context,
)
from src.parsers.fact_find_workflow.complaint_refs import all_refs, load_ref_groups
from src.parsers.fact_find_workflow.gate_validation import is_valid_complaint_ref, parse as parse_gate
from src.parsers.fact_find_workflow.summary_vs_aggregate import parse as parse_summary
from src.parsers.trace_parser import load_raw_trace

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "data/fact_find_workflow/aggregated_payloads/NC10010556.json"
REFS = ROOT / "data/fact_find_workflow/complaint-references.json"
TRACE_DIR = ROOT / "outputs/traces/fact_find_workflow/sanity"


def test_complaint_references_file():
    groups = load_ref_groups(REFS)
    assert "NC10010556" in groups["positive"]
    assert groups["negative"]
    assert "NC10010556" in all_refs(REFS, groups=["positive"])


def test_complaint_ref_format():
    assert is_valid_complaint_ref("NC10010556")
    assert not is_valid_complaint_ref("please look up NC10010556 for me")
    assert not is_valid_complaint_ref("NC123")


def test_aggregated_payload_context():
    payload = load_aggregated_payload(PAYLOAD)
    facts = extract_expected_facts(payload)
    context = payload_to_context(payload)
    assert facts["complaint_ref"] == "NC10010556"
    assert facts["party_id"] == "68905187"
    assert "Monica" in facts["customer_name"]
    assert any("77110361403060" in c for c in context)
    assert any("Support needs" in c for c in context)


def test_stage1_success_trace():
    raw = load_raw_trace(TRACE_DIR / "TC_001.json")
    parsed = parse_gate(raw)
    assert parsed.complaint_ref == "NC10010556"
    assert not parsed.validation_failed
    assert parsed.looks_like_summary
    assert parsed.successful_run is True


def test_stage1_invalid_trace():
    raw = load_raw_trace(TRACE_DIR / "TC_002.json")
    parsed = parse_gate(raw)
    assert parsed.validation_failed
    assert parsed.is_invalid_complaint_message
    assert not parsed.looks_like_summary


def test_stage2_success_grounding():
    raw = load_raw_trace(TRACE_DIR / "TC_001.json")
    parsed = parse_summary(
        raw,
        aggregated_payload_path=str(PAYLOAD),
    )
    assert parsed.has_customer_profile_section
    assert parsed.has_support_needs_section
    assert parsed.has_account_holdings_section
    assert parsed.has_contact_notes_section
    assert parsed.mentioned_party_id
    assert parsed.mentioned_complaint_ref
    assert parsed.mentioned_account_number
    assert parsed.mentioned_customer_name
    assert parsed.mentioned_dob
    assert parsed.mentioned_postcode
    assert parsed.support_needs_hit_count >= int(0.8 * parsed.support_needs_total)
    assert parsed.marks_complaint_associated_account
    assert parsed.mentions_no_trusted_party
    assert not parsed.invents_trusted_party
    assert parsed.mentioned_related_party_id


def test_expected_facts_include_support_needs():
    payload = load_aggregated_payload(PAYLOAD)
    facts = extract_expected_facts(payload)
    assert facts["support_need_count"] >= 1
    assert "3P - 3rd Party Mandate" in facts["support_need_descriptions"]
    assert facts["trusted_parties_failed"] is True
    assert "158010138" in facts["related_party_ids"]
