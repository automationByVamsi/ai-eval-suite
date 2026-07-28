"""Party ID resolution across ICA + account-details (mirrors party-resolver.ts)."""

from __future__ import annotations

from typing import Any

PartyId = str


class PartyResolver:
    """Resolve and deduplicate party ids from multiple backend sources."""
    @staticmethod
    def pick_primary_party_id(ica_response: Any) -> PartyId | None:
        """Prefer the primary ICA customer, then fall back to the first valid id."""
        customers = ica_response.get("customers") if isinstance(ica_response, dict) else None
        if not isinstance(customers, list):
            return None
        for customer in customers:
            if customer.get("customerPrimaryIndicator") and customer.get("customerOCISID") is not None:
                return str(customer["customerOCISID"])
        for customer in customers:
            if customer.get("customerOCISID") is not None:
                return str(customer["customerOCISID"])
        return None

    @staticmethod
    def get_all_party_ids(ica_response: Any) -> list[PartyId]:
        """Return unique OCIS ids found in the ICA customer list."""
        customers = ica_response.get("customers") if isinstance(ica_response, dict) else None
        if not isinstance(customers, list):
            return []
        ids: list[PartyId] = []
        seen: set[str] = set()
        for customer in customers:
            ocis = customer.get("customerOCISID")
            if ocis is None:
                continue
            text = str(ocis)
            if text not in seen:
                seen.add(text)
                ids.append(text)
        return ids

    @staticmethod
    def resolve_party_ids(
        party_ids_from_account_details: list[PartyId] | PartyId | None,
        ocis_party_id: PartyId | None,
        party_ids_from_ica: list[PartyId],
    ) -> dict[str, Any]:
        """Choose a primary party id and return a deduplicated ordered list."""
        if isinstance(party_ids_from_account_details, list):
            account_detail_party_ids = [str(p) for p in party_ids_from_account_details if p]
        elif party_ids_from_account_details:
            account_detail_party_ids = [str(party_ids_from_account_details)]
        else:
            account_detail_party_ids = []

        primary = ocis_party_id or (account_detail_party_ids[0] if account_detail_party_ids else None)
        if primary is None and party_ids_from_ica:
            primary = party_ids_from_ica[0]

        resolved: list[PartyId] = []
        seen: set[str] = set()
        for value in [primary, *account_detail_party_ids, *party_ids_from_ica]:
            if not value:
                continue
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            resolved.append(text)

        return {"primaryPartyId": primary, "resolvedPartyIds": resolved}
