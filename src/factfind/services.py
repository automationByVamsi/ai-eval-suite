"""Fact Find backend service wrappers (one call per system)."""

from __future__ import annotations

from typing import Any

from src.factfind import config
from src.factfind.http_client import FactFindHttpClient


def get_ica_case_details(client: FactFindHttpClient, complaint_ref: str) -> Any:
    endpoints = config.Endpoints.from_env()
    return client.get(
        endpoints.ica_case_details(complaint_ref),
        headers=config.get_nucleus_api_headers(),
    )


def get_account_details(client: FactFindHttpClient, account_number: str) -> Any:
    """
    Counter Account Details API.

    Request body mirrors the Playwright service: accountNumber as the 14-digit key.
    Response is normalised to {statusCode, details} when the API returns the
    details object directly.
    """
    endpoints = config.Endpoints.from_env()
    body = {"accountNumber": str(account_number).strip()[:14]}
    raw = client.post(
        endpoints.account_details,
        headers=config.get_counter_api_headers(),
        json_body=body,
    )
    if isinstance(raw, dict) and "details" in raw:
        return raw
    if isinstance(raw, dict) and "statusCode" in raw:
        return raw
    return {"statusCode": 200, "details": raw}


def get_customer_holding(client: FactFindHttpClient, party_id: str) -> Any:
    endpoints = config.Endpoints.from_env()
    return client.post(
        endpoints.customer_holding,
        headers=config.get_counter_api_headers(),
        json_body={"partyId": str(party_id), "criterion": "ALL"},
    )


def get_contact_notes(client: FactFindHttpClient, party_id: str) -> list[Any]:
    endpoints = config.Endpoints.from_env()
    body = client.get(
        endpoints.contact_notes(party_id),
        headers=config.get_ocis_api_headers(),
    )
    return body if isinstance(body, list) else []


def get_trusted_parties(client: FactFindHttpClient, party_id: str) -> list[Any]:
    endpoints = config.Endpoints.from_env()
    body = client.get(
        endpoints.trusted_parties(party_id),
        headers=config.get_ocis_api_headers(),
    )
    return body if isinstance(body, list) else []
