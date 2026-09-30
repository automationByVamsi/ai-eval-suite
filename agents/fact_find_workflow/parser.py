"""
Fact Find: build judge fields from the trace + the ground-truth payload, and check the
summary against the ground truth.

A success case points at its ground truth:   "expected": {"ground_truth": "ground_truth/NC10010556.json"}
That payload becomes `contexts` (for faithfulness and the rubrics) and `source_document`
(for summarization), and its key facts are checked deterministically in checks().
"""

import json
from pathlib import Path

from src.core.results import check
from src.utils.adk_trace import state, tool_calls

HERE = Path(__file__).parent
INVALID_MARKERS = ("InvalidComplaintId", "valid complaint reference must begin")
SUMMARY_MARKERS = ("FactFind Summary", "Complaint Reference")


def parse(trace, case):
    ref = case["input"]["complaint_ref"]
    answer = trace.get("agentOutput") or ""
    is_invalid = any(m in answer for m in INVALID_MARKERS)
    payload = _ground_truth(case)
    contexts = payload_to_context(payload) if payload else []
    calls = tool_calls(trace)
    return {
        # The judges' "question" is the task, not the bare reference number.
        "question": f"Produce a Customer FactFind Summary for complaint reference {ref}",
        "contexts": contexts,
        "source_document": "\n\n".join(contexts),
        "invalid_message": answer if is_invalid else "",   # only invalid-path cases get validation_message_clarity
        "is_invalid_message": is_invalid,
        "looks_like_summary": any(m in answer for m in SUMMARY_MARKERS),
        "validation_failed": bool(state(trace, "complaint_validation_failed", False)),
        "tools_called": [c["name"] for c in calls],
        "party_id_used": next((str(c["args"]["partyId"]) for c in calls if c["args"].get("partyId")), ""),
        "facts": key_facts(payload) if payload else {},
    }


def checks(fields, case):
    expected, answer, ref = case["expected"], fields["answer"], case["input"]["complaint_ref"]
    path = expected.get("path")
    results = []

    if path == "invalid_complaint":
        results.append(check("invalid_complaint_signal", fields["validation_failed"] or fields["is_invalid_message"],
                             "no InvalidComplaintId signal"))
        results.append(check("not_a_summary", not fields["looks_like_summary"], "invalid ref still produced a summary"))
        return results

    if path == "success":
        results.append(check("looks_like_summary", fields["looks_like_summary"], "answer is not a FactFind summary"))
        results.append(check("not_rejected", not (fields["validation_failed"] or fields["is_invalid_message"]),
                             "valid complaint ref was rejected"))
        results.append(check("complaint_ref_in_answer", ref in answer, f"{ref} missing from summary"))
        for tool in expected.get("expected_tools") or []:
            if fields["tools_called"]:  # only when the trace records tool calls
                results.append(check(f"tool_called:{tool}", tool in fields["tools_called"], f"{tool} not called"))

    # Ground-truth facts that must appear in the summary
    facts = fields["facts"]
    for name, value in [("party_id", facts.get("party_id")),
                        ("account_number", facts.get("account_number")),
                        ("date_of_birth", facts.get("date_of_birth")),
                        ("postcode", facts.get("postcode"))]:
        if value:
            results.append(check(f"fact:{name}", str(value) in answer, f"{name} {value!r} missing from summary"))
    if facts.get("name_tokens"):
        hits = sum(t.lower() in answer.lower() for t in facts["name_tokens"])
        results.append(check("fact:customer_name", hits >= min(2, len(facts["name_tokens"])),
                             f"customer name {' '.join(facts['name_tokens'])!r} missing"))
    for need in facts.get("support_needs") or []:
        results.append(check(f"fact:support_need:{need}", need.lower() in answer.lower(),
                             f"support need {need!r} missing"))
    return results


# --- Ground truth -----------------------------------------------------------------------------

def _ground_truth(case):
    rel = case["expected"].get("ground_truth")
    if not rel:
        return None
    return json.loads((HERE / rel).read_text())


def key_facts(payload):
    """The facts a correct summary must mention, taken from the aggregated payload."""
    derived, sources = payload.get("derived") or {}, payload.get("sources") or {}
    primary = str(derived.get("primaryPartyId") or "")
    holding = (((sources.get("customerHolding") or {}).get("customerHoldingsByParty")) or {}).get(primary) or {}
    party = holding.get("party") or {}
    name = f"{party.get('title', '')} {party.get('foreName', '')} {party.get('lastName', '')}"
    return {
        "party_id": primary,
        "account_number": str(derived.get("accountNumberFull") or ""),
        "date_of_birth": _date(party.get("dateOfBirth")),
        "postcode": (party.get("address") or {}).get("postcode"),
        "name_tokens": [t for t in name.split() if len(t) > 1],
        "support_needs": [n["description"] for n in (party.get("partyIndicator") or {}).get("supportNeeds") or []
                          if n.get("description")],
    }


def payload_to_context(payload):
    """Ground-truth payload -> readable text chunks, one per summary section."""
    derived, sources = payload.get("derived") or {}, payload.get("sources") or {}
    chunks = [f"Complaint reference: {payload.get('complaintRef', '')}\n"
              f"Primary party ID: {derived.get('primaryPartyId')}\n"
              f"Account number full: {derived.get('accountNumberFull')}"]

    ica = sources.get("ica") or {}
    header = ica.get("header") or {}
    if header:
        chunks.append(f"ICA case: {header.get('caseReference')}, status {header.get('caseStatusDescr')}, "
                      f"brand {header.get('caseBrandDescr')}, in bank since {header.get('caseDateInBank')}")
    for c in ica.get("customers") or []:
        chunks.append(f"ICA customer: {c.get('customerNameTitleDescr', '')} {c.get('customerFirstName', '')} "
                      f"{c.get('customerLastName', '')} (OCIS {c.get('customerOCISID')}, "
                      f"primary={c.get('customerPrimaryIndicator')})")

    holdings = ((sources.get("customerHolding") or {}).get("customerHoldingsByParty")) or {}
    for party_id, holding in holdings.items():
        if not isinstance(holding, dict) or holding.get("error"):
            continue
        party = holding.get("party") or {}
        address = party.get("address") or {}
        chunks.append("\n".join([
            f"Customer profile (party {party_id}):",
            f"  Name: {party.get('title', '')} {party.get('foreName', '')} {party.get('lastName', '')}",
            f"  Address: {', '.join([*(address.get('addressLines') or []), address.get('postcode') or ''])}",
            f"  Date of birth: {_date(party.get('dateOfBirth'))} (age {party.get('age')})",
            f"  Marital status: {party.get('maritalStatus')}",
            f"  Party ID created: {_date(party.get('timeWithBankDate'))}",
        ]))
        for need in (party.get("partyIndicator") or {}).get("supportNeeds") or []:
            chunks.append(f"Support need (party {party_id}): {need.get('description')}; recorded "
                          f"{_date(need.get('dateRecorded'))}; review {_date(need.get('dateForReview')) or 'ongoing'}; "
                          f"consent {need.get('consentStatus')}; info: {need.get('furtherInformation')}")
        for rel in party.get("relatedPartyList") or []:
            chunks.append(f"Related party (party {party_id}): {rel.get('relationshipDescription')} "
                          f"{rel.get('relatedPartyId')} ({rel.get('relatedPartyType')})")
        for product in holding.get("product") or []:
            chunks.append(f"Account (party {party_id}): {product.get('accountName')} "
                          f"{str(product.get('accountNumber') or '')[:14]}, status {product.get('accountStatus')}, "
                          f"opened {_date(product.get('accountOpenedDate'))}, "
                          f"role {product.get('productHeldRoleType')}")

    for account, wrap in (sources.get("accountDetails") or {}).items():
        details = (wrap or {}).get("details") or {}
        balance = details.get("balance") or {}
        chunks.append(f"Account details ({account}): valid {details.get('validAccount')}, "
                      f"booked balance {balance.get('interimBookedBalance')}, "
                      f"available {balance.get('interimAvailableBalance')}, "
                      f"overdraft {balance.get('overdraftAmount')} {balance.get('overdraftCurrencyCode') or ''}")

    for note in (sources.get("contactNotes") or [])[:20]:
        chunks.append(f"Contact note {note.get('contactDate')} {note.get('contactTime')}: "
                      f"{note.get('directionOfContactNarrative') or note.get('directionOfContact')}, "
                      f"{note.get('methodOfContactNarrative') or note.get('methodOfContact')}, "
                      f"{note.get('contactDetails') or note.get('notes') or ''}")

    for party_id, wrap in (sources.get("trustedPartiesByParty") or {}).items():
        if isinstance(wrap, dict) and wrap.get("error"):
            chunks.append(f"Trusted parties (party {party_id}): lookup failed")
        else:
            parties = wrap.get("trustedParties") if isinstance(wrap, dict) else wrap
            chunks.append(f"Trusted parties (party {party_id}): {parties or 'none'}")
    return chunks


def _date(value):
    """YYYY-MM-DD -> DD/MM/YYYY (how the agent prints dates)."""
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text[:10].split("-")
        return f"{d}/{m}/{y}"
    return text
