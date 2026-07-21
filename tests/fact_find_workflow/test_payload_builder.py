"""Offline unit tests for Fact Find aggregated-payload builders (no live APIs)."""

from src.factfind.data_fetcher import DataFetcher
from src.factfind.party_resolver import PartyResolver
from src.factfind.payload_builder import PayloadBuilder


def test_party_resolver_primary_and_all():
    ica = {
        "customers": [
            {"customerOCISID": 111, "customerPrimaryIndicator": False},
            {"customerOCISID": 222, "customerPrimaryIndicator": True},
        ]
    }
    assert PartyResolver.pick_primary_party_id(ica) == "222"
    assert PartyResolver.get_all_party_ids(ica) == ["111", "222"]


def test_resolve_party_ids_priority():
    resolved = PartyResolver.resolve_party_ids(["999"], "222", ["111", "222"])
    assert resolved["primaryPartyId"] == "222"
    assert resolved["resolvedPartyIds"] == ["222", "999", "111"]


def test_normalize_account_key():
    assert DataFetcher.normalize_account_key("7711036140306000000") == "77110361403060"
    assert DataFetcher.is_eligible_product_type("CURRENT_ACCOUNT")


def test_extract_party_ids_for_account():
    holdings = {
        "222": {
            "product": [
                {
                    "accountNumber": "77110361403060",
                    "productType": "CURRENT_ACCOUNT",
                    "partyList": [{"partyId": 222}, {"partyId": 333}],
                }
            ]
        }
    }
    assert set(DataFetcher.extract_party_ids_for_account(holdings, 77110361403060)) == {
        "222",
        "333",
    }


def test_payload_builder_shape():
    derived = PayloadBuilder.build_derived_metadata(
        account_number_full=77110361403060,
        ocis_party_id="222",
        party_id_from_account_details="222",
        primary_party_id="222",
        party_ids_from_ica=["222"],
        resolved_party_ids=["222"],
        customer_flow_party_ids=["222"],
        account_details_skipped=False,
        customer_holdings_by_party={"222": {"product": []}},
        contact_notes_by_party={"222": {"notes": [{"n": 1}], "error": None}},
        trusted_parties_by_party={
            "222": {"trustedParties": [], "error": {"message": "fail", "timestamp": "t"}}
        },
    )
    assert derived["partyIdUsed"] == "222"
    assert derived["failedTrustedPartiesPartyIds"] == ["222"]
    assert derived["failedContactNotesPartyIds"] == []

    sources = PayloadBuilder.build_sources(
        ica_response={"header": {}},
        account_details_map={},
        customer_holdings_by_party={"222": {"product": []}},
        contact_notes_by_party={"222": {"notes": [{"n": 1}], "error": None}},
        trusted_parties_by_party={"222": {"trustedParties": [], "error": None}},
        customer_flow_party_ids=["222"],
    )
    assert sources["contactNotes"] == [{"n": 1}]
    assert "customerHoldingsByParty" in sources["customerHolding"]

    final = PayloadBuilder.build_final_payload(
        complaint_ref="NC10010556", derived=derived, sources=sources
    )
    assert final["complaintRef"] == "NC10010556"
    assert set(final.keys()) >= {
        "complaintRef",
        "generatedAt",
        "counterApiVersion",
        "derived",
        "sources",
    }
