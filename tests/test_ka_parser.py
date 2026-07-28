"""Smoke tests for Knowledge Agent field extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.agent_response import AgentResponse
from src.parsers.knowledge_agent import enrich, extract

TRACE_DIR = Path("outputs/traces/knowledge_agent/sanity")


@pytest.mark.parametrize("case_id", ["TC_001", "TC_002"])
def test_extract_from_sanity_trace(case_id: str):
    path = TRACE_DIR / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"missing trace {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    view = extract(data)

    assert view.answer
    assert view.rewritten_query
    assert view.anchor_page_id
    assert view.question


def test_enrich_puts_fields_on_metadata():
    path = TRACE_DIR / "TC_001.json"
    if not path.is_file():
        pytest.skip(f"missing trace {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("raw_output", data)
    response = AgentResponse(answer="placeholder", raw_output=raw)
    enriched = enrich(response, question="How do I support someone gambling?")

    assert enriched.metadata["rewritten_query"]
    assert enriched.metadata["anchor_page_id"] == "9001"
    assert enriched.metadata["question"] == "How do I support someone gambling?"
    assert enriched.answer  # filled from view when useful
