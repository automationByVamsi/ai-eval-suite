"""
PayloadBuilder — assemble aggregated ground-truth JSON.

Mirrors factfind/src/orchestrator/helpers/payload-builder.ts
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agents.fact_find_workflow import config

PartyId = str


class PayloadBuilder:
    @staticmethod
    def build_derived_metadata(
        *,
        account_number_full: Any,
        ocis_party_id: PartyId | None,
        party_id_from_account_details: PartyId | None,
        primary_party_id: PartyId | None,
        party_ids_from_ica: list[PartyId],
        resolved_party_ids: list[PartyId],
        customer_flow_party_ids: list[PartyId],
        account_details_skipped: bool,
        customer_holdings_by_party: dict[str, Any],
        contact_notes_by_party: dict[str, Any],
        trusted_parties_by_party: dict[str, Any],
    ) -> dict[str, Any]:
        failed_holdings = [
            pid
            for pid in customer_flow_party_ids
            if isinstance(customer_holdings_by_party.get(pid), dict)
            and customer_holdings_by_party[pid].get("error")
        ]
        failed_notes = [
            pid
            for pid in customer_flow_party_ids
            if isinstance(contact_notes_by_party.get(pid), dict)
            and contact_notes_by_party[pid].get("error")
        ]
        failed_trusted = [
            pid
            for pid in customer_flow_party_ids
            if isinstance(trusted_parties_by_party.get(pid), dict)
            and trusted_parties_by_party[pid].get("error")
        ]
        empty_flow = len(customer_flow_party_ids) == 0
        return {
            "accountNumberFull": account_number_full,
            "ocisPartyId": ocis_party_id,
            "partyIdFromAccountDetails": party_id_from_account_details,
            "primaryPartyId": primary_party_id,
            "partyIdUsed": primary_party_id,
            "partyIdsFromIca": party_ids_from_ica,
            "resolvedPartyIds": resolved_party_ids,
            "customerFlowPartyIds": customer_flow_party_ids,
            "accountDetailsSkipped": account_details_skipped,
            "customerHoldingSkipped": not bool(primary_party_id),
            "customerHoldingsByPartySkipped": empty_flow,
            "contactNotesSkipped": empty_flow,
            "trustedPartiesSkipped": empty_flow,
            "failedCustomerHoldingPartyIds": failed_holdings,
            "failedContactNotesPartyIds": failed_notes,
            "failedTrustedPartiesPartyIds": failed_trusted,
        }

    @staticmethod
    def build_sources(
        *,
        ica_response: Any,
        account_details_map: dict[str, Any],
        customer_holdings_by_party: dict[str, Any],
        contact_notes_by_party: dict[str, Any],
        trusted_parties_by_party: dict[str, Any],
        customer_flow_party_ids: list[PartyId],
    ) -> dict[str, Any]:
        flattened_notes: list[Any] = []
        for party_id in customer_flow_party_ids:
            wrap = contact_notes_by_party.get(party_id) or {}
            notes = wrap.get("notes") if isinstance(wrap, dict) else None
            if isinstance(notes, list):
                flattened_notes.extend(notes)

        flattened_trusted: list[Any] = []
        for party_id in customer_flow_party_ids:
            wrap = trusted_parties_by_party.get(party_id) or {}
            trusted = wrap.get("trustedParties") if isinstance(wrap, dict) else None
            if isinstance(trusted, list):
                flattened_trusted.extend(trusted)

        return {
            "ica": ica_response if ica_response is not None else {},
            "accountDetails": account_details_map,
            "customerHolding": {"customerHoldingsByParty": customer_holdings_by_party},
            "contactNotes": flattened_notes,
            "contactNotesByParty": contact_notes_by_party,
            "trustedParties": flattened_trusted,
            "trustedPartiesByParty": trusted_parties_by_party,
        }

    @staticmethod
    def build_final_payload(
        *,
        complaint_ref: str,
        derived: dict[str, Any],
        sources: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "complaintRef": complaint_ref,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "counterApiVersion": config.counter_api_version(),
            "derived": derived,
            "sources": sources,
        }
