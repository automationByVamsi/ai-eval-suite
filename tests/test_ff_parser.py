"""Fact Find parser tests — pinned to ff_org_adk.json (full live shape)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.agent_response import AgentResponse
from src.parsers.fact_find_workflow import enrich, extract

ORG = Path("ff_org_adk.json")
CURR_SLIM = Path("ff_curr_adk.json")
TRACE_DIR = Path("outputs/traces/fact_find_workflow/sanity")


def test_extract_full_org_trace():
    if not ORG.is_file():
        pytest.skip("ff_org_adk.json not in repo root")

    view = extract(json.loads(ORG.read_text(encoding="utf-8")))

    assert view.complaint_ref == "NC10010556"
    assert view.looks_like_summary
    assert not view.validation_failed
    assert not view.is_invalid_message
    assert "getCustomerSummary" in view.tool_names
    assert "getContactNotes" in view.tool_names
    assert view.party_id == "68905187"
    assert view.account_number == "77110361403060"
    assert view.answer.startswith("# Customer FactFind Summary") or "FactFind Summary" in view.answer


def test_enrich_from_org_trace():
    if not ORG.is_file():
        pytest.skip("ff_org_adk.json not in repo root")

    raw = json.loads(ORG.read_text(encoding="utf-8"))
    response = enrich(AgentResponse(answer="", raw_output=raw))

    assert response.metadata["complaint_ref"] == "NC10010556"
    assert "getCustomerSummary" in response.metadata["tool_names"]
    assert response.metadata["tools_called"]
    assert response.answer


def test_slim_replay_trace_still_parses():
    """Older slim traces (no tools) must not crash — tool lists stay empty."""
    path = CURR_SLIM if CURR_SLIM.is_file() else TRACE_DIR / "TC_001.json"
    if not path.is_file():
        pytest.skip(f"missing {path}")

    view = extract(json.loads(path.read_text(encoding="utf-8")), complaint_ref="NC10010556")
    assert view.answer
    assert view.looks_like_summary
    # slim / replay may have no tool events
    assert isinstance(view.tool_names, tuple)


def test_invalid_complaint_from_cached_tc002():
    path = TRACE_DIR / "TC_002.json"
    if not path.is_file():
        pytest.skip(f"missing {path}")

    view = extract(json.loads(path.read_text(encoding="utf-8")), complaint_ref="NC")
    assert view.validation_failed or view.is_invalid_message
    assert not view.looks_like_summary
