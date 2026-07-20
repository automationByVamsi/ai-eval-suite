"""
Unit tests for the generic ADK trace primitives in adk_parser.py, run
directly against a real captured trace (sample-agent-response.json) so each
helper's behavior is pinned to an actual ADK event shape, not a hand-wavy
mock. These are the "fetching" primitives every stage-specific parser
(e.g. src/parsers/knowledge_agent/stage1.py) is built on top of.
"""

import json
from pathlib import Path

import pytest

from src.agents import adk_parser

RAW = json.loads(Path("sample-agent-response.json").read_text())


def test_extract_answer_reads_the_agent_output_field():
    assert adk_parser.extract_answer(RAW) == RAW["agentOutput"]
    assert adk_parser.extract_answer(RAW).startswith("### anchor page")


def test_extract_answer_defaults_to_empty_string_when_missing():
    assert adk_parser.extract_answer({}) == ""


def test_extract_context_reads_the_context_list():
    context = adk_parser.extract_context(RAW)
    assert len(context) == 2
    assert "Requesting VPN Access" in context[0]


def test_extract_context_defaults_to_empty_list_when_missing():
    assert adk_parser.extract_context({}) == []


def test_extract_events_reads_raw_events():
    events = adk_parser.extract_events(RAW)
    assert len(events) == len(RAW["raw_events"])
    assert events[0]["author"] == "knowledge_agent_workflow"


def test_extract_events_defaults_to_empty_list_when_missing():
    assert adk_parser.extract_events({}) == []


def test_extract_session_id_reads_sessionId():
    assert adk_parser.extract_session_id(RAW) == "8f1a9aaa-b3ef-4a95-80bb-292446250423"


def test_extract_latency_ms_reads_latency_ms():
    assert adk_parser.extract_latency_ms(RAW) == pytest.approx(20458.100916002877)


def test_find_event_by_author_returns_the_first_match():
    event = adk_parser.find_event_by_author(RAW, "query_rewrite_agent")
    assert event is not None
    assert event["id"] == "3487c252-890e-476e-b52f-842901fa6824"


def test_find_event_by_author_returns_none_when_no_author_matches():
    assert adk_parser.find_event_by_author(RAW, "nonexistent_agent") is None


def test_event_json_parses_the_models_json_text_output():
    event = adk_parser.find_event_by_author(RAW, "query_rewrite_agent")
    assert adk_parser.event_json(event) == {"rewritten_query": "VPN remote access request procedure"}


def test_event_json_returns_empty_dict_for_non_json_text():
    plain_text_event = {"content": {"parts": [{"text": "not json"}]}}
    assert adk_parser.event_json(plain_text_event) == {}


def test_event_json_returns_empty_dict_when_event_has_no_content():
    assert adk_parser.event_json({}) == {}


def test_state_after_returns_the_last_written_value_across_events():
    # query_rewrite_agent's own stateDelta is empty ({}) - the write only
    # shows up one event later, in search_engine_workflow's stateDelta, and
    # then keeps recurring in every event after that.
    assert adk_parser.state_after(RAW, "rewritten_query") == "VPN remote access request procedure"
    assert adk_parser.state_after(RAW, "anchor_page_id") == "8194"


def test_state_after_returns_none_for_a_key_never_written():
    assert adk_parser.state_after(RAW, "does_not_exist") is None
