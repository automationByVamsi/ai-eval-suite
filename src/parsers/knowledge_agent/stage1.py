"""
Stage 1 — Query Rewrite & Search Execution.

One module per stage: typed model + parse() from the ADK trace.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.agents import adk_parser

_SEARCH_MSG_RE = re.compile(
    r"Search retrieved successfully\."
    r".*?artifact_id=(?P<artifact_id>\S+)"
    r".*?result_count=(?P<result_count>\d+)"
    r".*?deduplicated_page_ids=(?P<deduplicated_page_ids>\d+)",
    re.DOTALL,
)


class Stage1Parsed(BaseModel):
    """Stage 1 fields from strategy: rewrite + Athena search outputs."""

    question: str
    state_query: Optional[str] = None
    business_area: Optional[str] = None

    rewrite_ran: bool
    rewrite_finished_ok: bool = False
    rewritten_query: Optional[str] = None
    state_rewritten_query: Optional[str] = None
    carried_into_state: bool

    search_ran: bool = False
    search_succeeded: bool = False
    artifact_id: Optional[str] = None
    result_count: Optional[int] = None
    deduplicated_page_ids_count: Optional[int] = None

    answer: str = ""
    context: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    latency_ms: Optional[float] = None


def _event_text(event: dict[str, Any] | None) -> str:
    if not event:
        return ""
    parts = event.get("content", {}).get("parts", [])
    return parts[0].get("text", "") if parts else ""


def _find_event_by_path_contains(raw: dict[str, Any], needle: str) -> dict[str, Any] | None:
    for event in adk_parser.extract_events(raw):
        path = (event.get("nodeInfo") or {}).get("path") or ""
        if needle in path:
            return event
    return None


def _parse_search_message(text: str) -> dict[str, Any]:
    match = _SEARCH_MSG_RE.search(text or "")
    if not match:
        return {}
    return {
        "artifact_id": match.group("artifact_id"),
        "result_count": int(match.group("result_count")),
        "deduplicated_page_ids_count": int(match.group("deduplicated_page_ids")),
    }


def parse(raw: dict[str, Any]) -> Stage1Parsed:
    """Raw captured trace → Stage1Parsed."""
    test_case = raw.get("test_case", {})
    agent_output = raw.get("raw_output", {})

    rewrite_event = adk_parser.find_event_by_author(agent_output, "query_rewrite_agent")
    rewritten_query = adk_parser.event_json(rewrite_event).get("rewritten_query") if rewrite_event else None
    state_rewritten_query = adk_parser.state_after(agent_output, "rewritten_query")
    state_query = adk_parser.state_after(agent_output, "query")
    business_area = adk_parser.state_after(agent_output, "business_area")

    search_event = _find_event_by_path_contains(agent_output, "search_node")
    search_text = _event_text(search_event)
    search_fields = _parse_search_message(search_text)
    artifact_id = search_fields.get("artifact_id") or adk_parser.state_after(agent_output, "artifact_id")

    finish_reason = (rewrite_event or {}).get("finishReason")
    rewrite_finished_ok = rewrite_event is not None and (
        finish_reason in (None, "STOP")  # STOP or absent on simplified traces
    )

    return Stage1Parsed(
        question=test_case.get("input", {}).get("question", "") or agent_output.get("question", ""),
        state_query=state_query if isinstance(state_query, str) else None,
        business_area=business_area if isinstance(business_area, str) else None,
        rewrite_ran=rewrite_event is not None,
        rewrite_finished_ok=rewrite_finished_ok,
        rewritten_query=rewritten_query if isinstance(rewritten_query, str) else None,
        state_rewritten_query=state_rewritten_query if isinstance(state_rewritten_query, str) else None,
        carried_into_state=bool(rewritten_query)
        and bool(state_rewritten_query)
        and state_rewritten_query == rewritten_query,
        search_ran=search_event is not None,
        search_succeeded="Search retrieved successfully" in search_text,
        artifact_id=artifact_id if isinstance(artifact_id, str) else None,
        result_count=search_fields.get("result_count"),
        deduplicated_page_ids_count=search_fields.get("deduplicated_page_ids_count"),
        answer=adk_parser.extract_answer(agent_output),
        context=adk_parser.extract_context(agent_output),
        events=adk_parser.extract_events(agent_output),
        session_id=adk_parser.extract_session_id(agent_output),
        latency_ms=adk_parser.extract_latency_ms(agent_output),
    )
