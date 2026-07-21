"""
Generate aggregated payloads (ground truth) by calling Fact Find backend APIs
in the same order as the Playwright orchestrator.

Usage:
  python -m scripts.generate_factfind_payloads
  python -m scripts.generate_factfind_payloads data/fact_find_workflow/complaint-references.json
  python -m scripts.generate_factfind_payloads --refs NC10010556
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from src.factfind import config
from src.factfind.data_fetcher import DataFetcher
from src.factfind.http_client import FactFindHttpClient
from src.factfind.party_resolver import PartyResolver
from src.factfind.payload_builder import PayloadBuilder
from src.factfind.services import get_account_details, get_ica_case_details
from src.parsers.fact_find_workflow.complaint_refs import load_ref_groups


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def generate_expected_payload(
    complaint_ref: str,
    *,
    client: FactFindHttpClient | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Call backends for one complaint ref and write
    data/fact_find_workflow/aggregated_payloads/{complaintRef}.json
    """
    client = client or FactFindHttpClient(
        cert_paths=config.cert_paths(),
        verify_tls=False,
        timeout_s=float(config.env("FACTFIND_HTTP_TIMEOUT_S", "60") or "60"),
        retries=int(config.env("FACTFIND_HTTP_RETRIES", "1") or "1"),
    )
    output_dir = output_dir or config.DEFAULT_OUTPUT_DIR

    # 1. ICA case details
    ica_response = get_ica_case_details(client, complaint_ref)
    items = ica_response.get("items") if isinstance(ica_response, dict) else None
    account_number_full = None
    if isinstance(items, list) and items:
        account_number_full = items[0].get("accountNumberFull")

    ocis_party_id = PartyResolver.pick_primary_party_id(ica_response)
    party_ids_from_ica = PartyResolver.get_all_party_ids(ica_response)

    # 2. Resolve party IDs (seed account details when ICA has an account)
    party_id_from_account_details: str | None = None
    party_ids_from_account_details: list[str] = []
    account_details_skipped = False
    seed_account_details_map: dict[str, Any] = {}

    if account_number_full:
        primary_account_details = get_account_details(client, str(account_number_full))
        details = (
            primary_account_details.get("details")
            if isinstance(primary_account_details, dict)
            else None
        ) or {}
        identifiers = details.get("partyIdentifiers") if isinstance(details, dict) else None
        if isinstance(identifiers, list):
            seen: set[str] = set()
            for ident in identifiers:
                pid = ident.get("partyId") if isinstance(ident, dict) else None
                if pid is None:
                    continue
                text = str(pid)
                if text not in seen:
                    seen.add(text)
                    party_ids_from_account_details.append(text)
        party_id_from_account_details = (
            party_ids_from_account_details[0] if party_ids_from_account_details else None
        )
        key = DataFetcher.normalize_account_key(account_number_full)
        if key:
            seed_account_details_map[key] = primary_account_details
    else:
        account_details_skipped = True

    resolved = PartyResolver.resolve_party_ids(
        party_ids_from_account_details,
        ocis_party_id,
        party_ids_from_ica,
    )
    primary_party_id = resolved["primaryPartyId"]
    resolved_party_ids = resolved["resolvedPartyIds"]

    unique_ica_party_ids = list(dict.fromkeys([p for p in party_ids_from_ica if p]))
    if unique_ica_party_ids:
        seed_party_ids_for_customer_flow = unique_ica_party_ids
    else:
        seed_party_ids_for_customer_flow = list(
            dict.fromkeys(
                [p for p in [*party_ids_from_account_details, *resolved_party_ids] if p]
            )
        )

    # Customer holdings (seed) → parties on complaint account → fill gaps
    customer_holdings_by_party = DataFetcher.fetch_customer_holdings(
        client, seed_party_ids_for_customer_flow
    )
    complaint_account_party_ids = DataFetcher.extract_party_ids_for_account(
        customer_holdings_by_party, account_number_full
    )
    party_ids_for_customer_flow = (
        complaint_account_party_ids or seed_party_ids_for_customer_flow
    )

    missing = [pid for pid in party_ids_for_customer_flow if pid not in customer_holdings_by_party]
    if missing:
        customer_holdings_by_party = {
            **customer_holdings_by_party,
            **DataFetcher.fetch_customer_holdings(client, missing),
        }

    # 3. Contact notes + trusted parties in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        notes_fut = pool.submit(
            DataFetcher.fetch_contact_notes, client, party_ids_for_customer_flow
        )
        trusted_fut = pool.submit(
            DataFetcher.fetch_trusted_parties, client, party_ids_for_customer_flow
        )
        contact_notes_by_party = notes_fut.result()
        trusted_parties_by_party = trusted_fut.result()

    account_details_map = DataFetcher.fetch_account_details(
        client, customer_holdings_by_party, seed_account_details_map
    )

    derived = PayloadBuilder.build_derived_metadata(
        account_number_full=account_number_full,
        ocis_party_id=ocis_party_id,
        party_id_from_account_details=party_id_from_account_details,
        primary_party_id=primary_party_id,
        party_ids_from_ica=party_ids_from_ica,
        resolved_party_ids=resolved_party_ids,
        customer_flow_party_ids=party_ids_for_customer_flow,
        account_details_skipped=account_details_skipped,
        customer_holdings_by_party=customer_holdings_by_party,
        contact_notes_by_party=contact_notes_by_party,
        trusted_parties_by_party=trusted_parties_by_party,
    )
    sources = PayloadBuilder.build_sources(
        ica_response=ica_response,
        account_details_map=account_details_map,
        customer_holdings_by_party=customer_holdings_by_party,
        contact_notes_by_party=contact_notes_by_party,
        trusted_parties_by_party=trusted_parties_by_party,
        customer_flow_party_ids=party_ids_for_customer_flow,
    )
    final_payload = PayloadBuilder.build_final_payload(
        complaint_ref=complaint_ref,
        derived=derived,
        sources=sources,
    )

    out_path = Path(output_dir) / f"{complaint_ref}.json"
    _write_json(out_path, final_payload)
    print(f"Aggregated payload written: {out_path}")
    return final_payload


def generate_all(
    refs_path: Path | None = None,
    *,
    groups: list[str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, int]:
    """
    Generate payloads for refs in complaint-references.json.

    Only `positive` (and optionally `edge`) groups call live APIs by default —
    `negative` entries are invalid inputs and are skipped.
    """
    refs_path = refs_path or config.DEFAULT_REFS_FILE
    ref_groups = load_ref_groups(refs_path)
    selected = groups or ["positive", "edge"]
    summary = {"succeeded": 0, "failed": 0, "skipped": 0}

    client = FactFindHttpClient(
        cert_paths=config.cert_paths(),
        verify_tls=False,
        timeout_s=float(config.env("FACTFIND_HTTP_TIMEOUT_S", "60") or "60"),
        retries=int(config.env("FACTFIND_HTTP_RETRIES", "1") or "1"),
    )
    output_dir = output_dir or config.DEFAULT_OUTPUT_DIR

    for group_name in selected:
        refs = ref_groups.get(group_name, [])
        if group_name == "negative":
            print(f"Skipping group '{group_name}' ({len(refs)} invalid input(s)) — no API ground truth")
            summary["skipped"] += len(refs)
            continue
        print(f"Generating aggregated payloads for group '{group_name}' ({len(refs)} reference(s))")
        for ref in refs:
            try:
                generate_expected_payload(ref, client=client, output_dir=output_dir)
                summary["succeeded"] += 1
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                print(f"  FAILED {ref}: {exc}")
        print(
            f"Completed group '{group_name}': "
            f"{summary['succeeded']} succeeded, {summary['failed']} failed"
        )
    return summary
