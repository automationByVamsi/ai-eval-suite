"""
Summary vs aggregate — Customer FactFind Summary quality vs ground truth.

Compares the agent's UI summary against the aggregated payload ground truth
(same JSON shape produced by the Playwright PayloadBuilder).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.agents import adk_parser
from src.parsers.fact_find_workflow.aggregated_payload import (
    extract_expected_facts,
    load_aggregated_payload,
    payload_to_context,
)
from src.parsers.fact_find_workflow.gate_validation import state_value
from src.parsers.fact_find_workflow.tool_calls import extract_tools_called, tool_calls_from_expected


class SummaryVsAggregateParsed(BaseModel):
    complaint_ref: str
    answer: str
    path: str = "success"  # success | invalid_complaint
    validation_failed: bool = False
    has_customer_profile_section: bool = False
    has_support_needs_section: bool = False
    has_account_holdings_section: bool = False
    has_related_parties_section: bool = False
    has_contact_notes_section: bool = False
    mentioned_party_id: bool = False
    mentioned_complaint_ref: bool = False
    mentioned_account_number: bool = False
    mentioned_customer_name: bool = False
    mentioned_dob: bool = False
    mentioned_postcode: bool = False
    mentioned_marital_status: bool = False
    support_needs_hit_count: int = 0
    support_needs_total: int = 0
    mentioned_related_party_id: bool = False
    mentions_no_trusted_party: bool = False
    invents_trusted_party: bool = False
    marks_complaint_associated_account: bool = False
    contact_note_dates_hit_count: int = 0
    tools_called: list[Any] = Field(default_factory=list)
    expected_tools: list[Any] = Field(default_factory=list)
    expected_facts: dict[str, Any] = Field(default_factory=dict)
    context: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    latency_ms: Optional[float] = None


def _section_present(answer: str, *needles: str) -> bool:
    lower = answer.lower()
    return any(n.lower() in lower for n in needles)


def _token_hits(answer: str, tokens: list[str], *, min_hits: int = 2) -> bool:
    if not tokens:
        return False
    lower = answer.lower()
    hits = sum(1 for t in tokens if t.lower() in lower)
    return hits >= min(min_hits, len(tokens))


def parse(raw: dict[str, Any], *, aggregated_payload_path: str | Path | None = None) -> SummaryVsAggregateParsed:
    test_case = raw.get("test_case", {})
    agent_output = raw.get("raw_output", {})
    expected = test_case.get("expected") or {}
    complaint_ref = (
        test_case.get("input", {}).get("complaint_ref")
        or agent_output.get("complaintRef")
        or ""
    )
    answer = adk_parser.extract_answer(agent_output)
    path = expected.get("path") or (
        "invalid_complaint"
        if state_value(agent_output, "complaint_validation_failed")
        else "success"
    )

    payload_path = aggregated_payload_path or expected.get("aggregated_payload_path")
    expected_facts: dict[str, Any] = {}
    context: list[str] = list(adk_parser.extract_context(agent_output) or [])

    if payload_path:
        payload = load_aggregated_payload(payload_path)
        expected_facts = extract_expected_facts(payload)
        if not context:
            context = payload_to_context(payload)

    party_id = str(expected_facts.get("party_id") or expected.get("party_id") or "")
    account_full = str(expected_facts.get("account_number_full") or "")
    account_tokens = [t for t in [account_full, *(expected_facts.get("account_numbers") or [])] if t]
    support_needs = [d for d in (expected_facts.get("support_need_descriptions") or []) if d]
    support_hits = sum(1 for desc in support_needs if desc and desc.lower() in answer.lower())
    related_ids = expected_facts.get("related_party_ids") or []
    note_dates = expected_facts.get("contact_note_dates") or []
    note_date_hits = sum(1 for d in note_dates if d and (_fmt_in_answer(answer, d)))

    trusted_failed = bool(expected_facts.get("trusted_parties_failed"))
    no_trusted_phrasing = _section_present(
        answer,
        "No Trusted Party",
        "No Trusted Party identified",
        "No Relationships identified",
        "none identified",
    )
    # Heuristic: inventing trusted parties when API failed — named "Trusted Party"
    # relationship with an ID that is not a known related-party id.
    invents_trusted = False
    if trusted_failed or expected_facts.get("trusted_parties_empty"):
        invents_trusted = (
            "trusted party" in answer.lower()
            and not no_trusted_phrasing
            and "no trusted" not in answer.lower()
            and any(ch.isdigit() for ch in answer)
            and not any(rid in answer for rid in related_ids)
        )

    return SummaryVsAggregateParsed(
        complaint_ref=str(complaint_ref),
        answer=answer,
        path=path,
        validation_failed=bool(state_value(agent_output, "complaint_validation_failed")),
        has_customer_profile_section=_section_present(answer, "Customer Profile", "Primary Customer"),
        has_support_needs_section=_section_present(answer, "Support Need", "Support Needs"),
        has_account_holdings_section=_section_present(
            answer, "Account Holdings", "Associated with complaint"
        ),
        has_related_parties_section=_section_present(
            answer, "Related Parties", "Trusted Party", "Attorney"
        ),
        has_contact_notes_section=_section_present(answer, "Contact Notes", "Contact date"),
        mentioned_party_id=bool(party_id) and party_id in answer,
        mentioned_complaint_ref=bool(complaint_ref) and str(complaint_ref) in answer,
        mentioned_account_number=any(token and token in answer for token in account_tokens),
        mentioned_customer_name=_token_hits(answer, list(expected_facts.get("customer_name_tokens") or [])),
        mentioned_dob=bool(expected_facts.get("date_of_birth"))
        and str(expected_facts.get("date_of_birth")) in answer,
        mentioned_postcode=bool(expected_facts.get("postcode"))
        and str(expected_facts.get("postcode")) in answer,
        mentioned_marital_status=bool(expected_facts.get("marital_status"))
        and str(expected_facts.get("marital_status")).lower() in answer.lower(),
        support_needs_hit_count=support_hits,
        support_needs_total=len(support_needs),
        mentioned_related_party_id=any(rid in answer for rid in related_ids),
        mentions_no_trusted_party=no_trusted_phrasing,
        invents_trusted_party=invents_trusted,
        marks_complaint_associated_account=_section_present(
            answer, "Associated with complaint", "associated with complaint"
        ),
        contact_note_dates_hit_count=note_date_hits,
        tools_called=extract_tools_called(agent_output),
        expected_tools=tool_calls_from_expected(expected.get("expected_tools")),
        expected_facts=expected_facts,
        context=context,
        events=adk_parser.extract_events(agent_output),
        session_id=adk_parser.extract_session_id(agent_output),
        latency_ms=adk_parser.extract_latency_ms(agent_output),
    )


def _fmt_in_answer(answer: str, iso_or_display: str) -> bool:
    """Match ISO YYYY-MM-DD or DD/MM/YYYY forms in the summary."""
    text = str(iso_or_display)
    if text in answer:
        return True
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text[:10].split("-")
        return f"{d}/{m}/{y}" in answer
    return False
