"""
DataFetcher — concurrent multi-party / multi-account fetches.

Mirrors factfind/src/orchestrator/helpers/data-fetcher.ts
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from src.agents.fact_find_workflow import config
from src.agents.fact_find_workflow.http_client import FactFindHttpClient
from src.agents.fact_find_workflow.services import get_account_details, get_contact_notes, get_customer_holding, get_trusted_parties

PartyId = str


def _now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _error_body(message: str) -> dict[str, Any]:
    """Wrap an error message with a timestamp."""
    return {"message": message, "timestamp": _now()}


def _holding_error_payload(message: str) -> dict[str, Any]:
    """Match the customer-holding error shape used elsewhere in the payload."""
    return {"error": _error_body(message)}


class DataFetcher:
    """Fetch Fact Find backend data and normalize the results."""
    @staticmethod
    def normalize_account_key(account_number: Any) -> str:
        """Trim an account number down to the 14-digit comparison key."""
        return str(account_number or "").strip()[:14]

    @staticmethod
    def is_eligible_product_type(product_type: Any) -> bool:
        """Return True when the product type should get account details."""
        return str(product_type or "").strip() in config.ELIGIBLE_PRODUCT_TYPES

    @classmethod
    def extract_party_ids_for_account(
        cls,
        customer_holdings_by_party: dict[str, Any],
        account_number_full: Any,
    ) -> list[PartyId]:
        """Find parties linked to the given account within holding responses."""
        target = cls.normalize_account_key(account_number_full)
        if not target:
            return []
        party_ids: set[str] = set()
        for holding in customer_holdings_by_party.values():
            products = holding.get("product") if isinstance(holding, dict) else None
            if not isinstance(products, list):
                continue
            for product in products:
                product_key = cls.normalize_account_key(product.get("accountNumber"))
                if not product_key or product_key != target:
                    continue
                party_list = product.get("partyList") if isinstance(product.get("partyList"), list) else []
                for party in party_list:
                    party_id = party.get("partyId") if isinstance(party, dict) else None
                    if party_id is not None and str(party_id).strip():
                        party_ids.add(str(party_id))
        return list(party_ids)

    @classmethod
    def extract_eligible_account_numbers(
        cls,
        customer_holdings_by_party: dict[str, Any],
    ) -> dict[str, str]:
        """Collect eligible account numbers keyed by their normalized form."""
        account_numbers: dict[str, str] = {}
        for holding in customer_holdings_by_party.values():
            products = holding.get("product") if isinstance(holding, dict) else None
            if not isinstance(products, list):
                continue
            for product in products:
                if not cls.is_eligible_product_type(product.get("productType")):
                    continue
                account_number_full = str(product.get("accountNumber") or "").strip()
                if not account_number_full:
                    continue
                key = cls.normalize_account_key(account_number_full)
                if key and key not in account_numbers:
                    account_numbers[key] = account_number_full
        return account_numbers

    @classmethod
    def fetch_customer_holdings(
        cls,
        client: FactFindHttpClient,
        party_ids: list[PartyId],
    ) -> dict[str, Any]:
        """Fetch customer-holding data for each party id in parallel."""
        if not party_ids:
            return {}

        def _one(party_id: str) -> tuple[str, Any]:
            """Fetch one party's holdings and wrap errors in the payload shape."""
            try:
                return party_id, get_customer_holding(client, party_id)
            except Exception as exc:  # noqa: BLE001
                return party_id, _holding_error_payload(str(exc) or "Unknown Customer Holding error")

        return cls._parallel_map(party_ids, _one)

    @classmethod
    def fetch_contact_notes(
        cls,
        client: FactFindHttpClient,
        party_ids: list[PartyId],
    ) -> dict[str, Any]:
        """Fetch contact notes for each party id in parallel."""
        if not party_ids:
            return {}

        def _one(party_id: str) -> tuple[str, Any]:
            """Fetch one party's contact notes and preserve per-party failures."""
            try:
                notes = get_contact_notes(client, party_id)
                return party_id, {"notes": notes, "error": None}
            except Exception as exc:  # noqa: BLE001
                return party_id, {
                    "notes": [],
                    "error": _error_body(str(exc) or "Unknown Contact Notes error"),
                }

        return cls._parallel_map(party_ids, _one)

    @classmethod
    def fetch_trusted_parties(
        cls,
        client: FactFindHttpClient,
        party_ids: list[PartyId],
    ) -> dict[str, Any]:
        """Fetch trusted-party data for each party id in parallel."""
        if not party_ids:
            return {}

        def _one(party_id: str) -> tuple[str, Any]:
            """Fetch one party's trusted-party data with error details when needed."""
            try:
                trusted = get_trusted_parties(client, party_id)
                return party_id, {"trustedParties": trusted, "error": None}
            except Exception as exc:  # noqa: BLE001
                return party_id, {
                    "trustedParties": [],
                    "error": _error_body(str(exc) or "Unknown Trusted Parties error"),
                }

        return cls._parallel_map(party_ids, _one)

    @classmethod
    def fetch_account_details(
        cls,
        client: FactFindHttpClient,
        customer_holdings_by_party: dict[str, Any],
        seed_map: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch missing account details for eligible accounts only."""
        details_map = dict(seed_map or {})
        eligible = cls.extract_eligible_account_numbers(customer_holdings_by_party)
        to_fetch = {k: v for k, v in eligible.items() if k not in details_map}
        if not to_fetch:
            return details_map

        def _one(item: tuple[str, str]) -> tuple[str, Any]:
            """Fetch one account's details keyed by the normalized account id."""
            key, account_number_full = item
            try:
                return key, get_account_details(client, account_number_full)
            except Exception as exc:  # noqa: BLE001
                return key, _holding_error_payload(str(exc) or "Unknown Account Details error")

        fetched = cls._parallel_map(list(to_fetch.items()), _one)
        details_map.update(fetched)
        return details_map

    @staticmethod
    def _parallel_map(items: list[Any], fn) -> dict[str, Any]:
        """Run a keyed worker function over items and collect the results."""
        if not items:
            return {}
        results: dict[str, Any] = {}
        workers = min(8, max(1, len(items)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fn, item) for item in items]
            for future in as_completed(futures):
                key, value = future.result()
                results[str(key)] = value
        return results
