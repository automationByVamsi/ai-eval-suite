"""
Load Fact Find aggregated payloads (ground truth) and flatten them into
retrieval-context strings for faithfulness / groundedness judges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_aggregated_payload(path: str | Path) -> dict[str, Any]:
    """Load one aggregated ground-truth payload from disk."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Aggregated payload must be a JSON object: {path}")
    return data


def _fmt_date(value: Any) -> str:
    """YYYY-MM-DD → DD/MM/YYYY when possible (matches ADK UI formatting)."""
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text[:10].split("-")
        return f"{d}/{m}/{y}"
    return text


def payload_to_context(payload: dict[str, Any]) -> list[str]:
    """
    Build retrieval_context chunks from an aggregated payload.

    Chunks mirror the Customer FactFind Summary sections shown in the ADK UI
    so faithfulness/groundedness judges can score the agent summary against
    the same ground truth used for UI validations in the Playwright suite.
    """
    chunks: list[str] = []
    complaint_ref = payload.get("complaintRef", "")
    derived = payload.get("derived") or {}
    sources = payload.get("sources") or {}

    chunks.append(
        "\n".join(
            [
                f"Complaint reference: {complaint_ref}",
                f"Counter API version: {payload.get('counterApiVersion', '')}",
                f"Primary party ID: {derived.get('primaryPartyId')}",
                f"Account number full: {derived.get('accountNumberFull')}",
                f"Resolved party IDs: {derived.get('resolvedPartyIds')}",
            ]
        )
    )

    ica = sources.get("ica") or {}
    header = ica.get("header") or {}
    if header:
        chunks.append(
            "\n".join(
                [
                    "ICA case header:",
                    f"  caseReference: {header.get('caseReference')}",
                    f"  caseStatus: {header.get('caseStatusDescr')}",
                    f"  caseBrand: {header.get('caseBrandDescr')}",
                    f"  caseDateInBank: {header.get('caseDateInBank')}",
                ]
            )
        )

    customers = ica.get("customers") or []
    if customers:
        lines = ["ICA customers:"]
        for c in customers:
            lines.append(
                f"  {c.get('customerNameTitleDescr', '')} "
                f"{c.get('customerFirstName', '')} {c.get('customerLastName', '')} "
                f"(OCIS {c.get('customerOCISID')}, primary={c.get('customerPrimaryIndicator')})"
            )
        chunks.append("\n".join(lines))

    holdings_by_party = ((sources.get("customerHolding") or {}).get("customerHoldingsByParty")) or {}
    for party_id, holding in holdings_by_party.items():
        if not isinstance(holding, dict) or holding.get("error"):
            continue
        party = holding.get("party") or {}
        address = party.get("address") or {}
        address_lines = address.get("addressLines") or []
        addr = ", ".join([*address_lines, address.get("postcode") or ""]).strip(", ")
        profile = "\n".join(
            [
                f"Customer profile (party {party_id}):",
                f"  Name: {party.get('title', '')} {party.get('foreName', '')} {party.get('lastName', '')}".strip(),
                f"  Party ID: {party.get('partyId')}",
                f"  Current address: {addr}",
                f"  Date of birth: {_fmt_date(party.get('dateOfBirth'))} (age {party.get('age')})",
                f"  Marital status: {party.get('maritalStatus')}",
                f"  Party ID created: {_fmt_date(party.get('timeWithBankDate'))}",
            ]
        )
        chunks.append(profile)

        support_needs = ((party.get("partyIndicator") or {}).get("supportNeeds")) or []
        if support_needs:
            sn_lines = [f"Support needs (party {party_id}):"]
            for need in support_needs:
                review = need.get("dateForReview")
                sn_lines.extend(
                    [
                        f"  Support Need: {need.get('description')}",
                        f"    Date recorded: {_fmt_date(need.get('dateRecorded'))}",
                        f"    Valid from: {_fmt_date(need.get('dateValidFrom'))}",
                        f"    Review date: {_fmt_date(review) if review else 'Ongoing (no date set)'}",
                        f"    Consent status: {need.get('consentStatus')}",
                        f"    Further information: {need.get('furtherInformation')}",
                    ]
                )
            chunks.append("\n".join(sn_lines))

        related = party.get("relatedPartyList") or []
        if related:
            rel_lines = [f"Related parties (party {party_id}):"]
            for rel in related:
                rel_lines.append(
                    f"  {rel.get('relationshipDescription')}: "
                    f"relatedPartyId={rel.get('relatedPartyId')} "
                    f"type={rel.get('relatedPartyType')}"
                )
            for note in party.get("relationshipNotifications") or []:
                rel_lines.append(f"  Notification: {note.get('notificationText')}")
            chunks.append("\n".join(rel_lines))

        products = holding.get("product") or []
        if products:
            prod_lines = [f"Account holdings (party {party_id}):"]
            for product in products:
                acct = str(product.get("accountNumber") or "")[:14]
                prod_lines.extend(
                    [
                        f"  {product.get('accountName')}: {acct}",
                        f"    Status: {product.get('accountStatus')}",
                        f"    Opened: {_fmt_date(product.get('accountOpenedDate'))}",
                        f"    Role: {product.get('productHeldRoleType')}",
                        f"    Product type: {product.get('productType')}",
                    ]
                )
            chunks.append("\n".join(prod_lines))

    account_details = sources.get("accountDetails") or {}
    for acct, detail_wrap in account_details.items():
        details = (detail_wrap or {}).get("details") or {}
        balance = details.get("balance") or {}
        chunks.append(
            "\n".join(
                [
                    f"Account details ({acct}):",
                    f"  validAccount: {details.get('validAccount')}",
                    f"  interimBookedBalance: {balance.get('interimBookedBalance')}",
                    f"  interimAvailableBalance: {balance.get('interimAvailableBalance')}",
                    f"  overdraftAmount: {balance.get('overdraftAmount')}",
                    f"  overdraftCurrencyCode: {balance.get('overdraftCurrencyCode')}",
                ]
            )
        )

    contact_notes = sources.get("contactNotes") or []
    if contact_notes:
        note_lines = ["Contact notes:"]
        for note in contact_notes[:20]:
            note_lines.extend(
                [
                    f"  {note.get('contactDate')} {note.get('contactTime')}:",
                    f"    Direction: {note.get('directionOfContactNarrative') or note.get('directionOfContact')}",
                    f"    Method: {note.get('methodOfContactNarrative') or note.get('methodOfContact')}",
                    f"    Location: {note.get('locationNarrative') or note.get('location')}",
                    f"    Classification: {note.get('classificationNarrative') or note.get('classification')}",
                    f"    Brand: {note.get('brandNarrative') or note.get('brand')}",
                    f"    Details: {note.get('contactDetails') or note.get('notes') or ''}",
                ]
            )
        chunks.append("\n".join(note_lines))

    trusted_by_party = sources.get("trustedPartiesByParty") or {}
    for party_id, wrap in trusted_by_party.items():
        if isinstance(wrap, dict) and wrap.get("error"):
            chunks.append(
                f"Trusted parties (party {party_id}): error — {wrap['error'].get('message', wrap['error'])}"
            )
            continue
        parties = wrap.get("trustedParties") if isinstance(wrap, dict) else wrap
        if not parties:
            chunks.append(f"Trusted parties (party {party_id}): none")
        else:
            lines = [f"Trusted parties (party {party_id}):"]
            for tp in parties:
                lines.append(f"  {tp}")
            chunks.append("\n".join(lines))

    return [c for c in chunks if c and c.strip()]


def extract_expected_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """Key facts used by deterministic groundedness / fidelity checks."""
    derived = payload.get("derived") or {}
    sources = payload.get("sources") or {}
    holdings = ((sources.get("customerHolding") or {}).get("customerHoldingsByParty")) or {}
    primary = str(derived.get("primaryPartyId") or "")
    party = (holdings.get(primary) or {}).get("party") or {}
    support_needs = ((party.get("partyIndicator") or {}).get("supportNeeds")) or []
    products = (holdings.get(primary) or {}).get("product") or []
    account_numbers = [str(p.get("accountNumber") or "")[:14] for p in products if p.get("accountNumber")]
    related = party.get("relatedPartyList") or []
    related_party_ids = [
        str(r.get("relatedPartyId"))
        for r in related
        if isinstance(r, dict) and r.get("relatedPartyId") is not None
    ]
    related_descriptions = [
        str(r.get("relationshipDescription"))
        for r in related
        if isinstance(r, dict) and r.get("relationshipDescription")
    ]

    trusted_by_party = sources.get("trustedPartiesByParty") or {}
    trusted_wrap = trusted_by_party.get(primary) if primary else None
    trusted_failed = bool(isinstance(trusted_wrap, dict) and trusted_wrap.get("error"))
    trusted_list = []
    if isinstance(trusted_wrap, dict) and not trusted_wrap.get("error"):
        trusted_list = trusted_wrap.get("trustedParties") or []

    contact_notes = sources.get("contactNotes") or []
    contact_note_dates = sorted(
        {
            str(n.get("contactDate"))
            for n in contact_notes
            if isinstance(n, dict) and n.get("contactDate")
        }
    )

    address = party.get("address") or {}
    address_lines = address.get("addressLines") or []
    name = f"{party.get('title', '')} {party.get('foreName', '')} {party.get('lastName', '')}".strip()
    name_tokens = [t for t in name.replace(",", " ").split() if len(t) > 1]

    return {
        "complaint_ref": payload.get("complaintRef"),
        "party_id": primary,
        "customer_name": name,
        "customer_name_tokens": name_tokens,
        "date_of_birth": _fmt_date(party.get("dateOfBirth")),
        "age": party.get("age"),
        "marital_status": party.get("maritalStatus"),
        "postcode": address.get("postcode"),
        "address_lines": address_lines,
        "support_need_descriptions": [n.get("description") for n in support_needs if n.get("description")],
        "support_need_count": len(support_needs),
        "account_numbers": account_numbers,
        "account_number_full": str(derived.get("accountNumberFull") or ""),
        "account_names": [p.get("accountName") for p in products if p.get("accountName")],
        "account_statuses": [p.get("accountStatus") for p in products if p.get("accountStatus")],
        "related_party_ids": related_party_ids,
        "related_party_descriptions": related_descriptions,
        "trusted_parties_failed": trusted_failed or primary in (derived.get("failedTrustedPartiesPartyIds") or []),
        "trusted_parties_empty": (not trusted_list) and not trusted_failed,
        "trusted_parties_count": len(trusted_list) if isinstance(trusted_list, list) else 0,
        "contact_note_count": len(contact_notes) if isinstance(contact_notes, list) else 0,
        "contact_note_dates": contact_note_dates,
        "failed_trusted_parties_party_ids": list(derived.get("failedTrustedPartiesPartyIds") or []),
        "failed_contact_notes_party_ids": list(derived.get("failedContactNotesPartyIds") or []),
        "failed_customer_holding_party_ids": list(derived.get("failedCustomerHoldingPartyIds") or []),
    }
