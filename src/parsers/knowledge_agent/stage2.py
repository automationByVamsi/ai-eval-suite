"""
Stage 2 — Anchor Node Identification.

Typed model + parse() from the ADK trace (same pattern as stage1.py).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.parsers import adk_parser

_ANCHOR_MSG_RE = re.compile(
    r"Anchor page selected using (?P<method>[\w\s]+?)method\s*\.?\s*anchor_page_id=(?P<anchor_page_id>\S+)",
    re.IGNORECASE,
)
_PAGE_ID_RE = re.compile(r"page_id:\s*(\d+)", re.IGNORECASE)
_HEADING_ID_RE = re.compile(r"####\s*(\d+)\s*\|")


class Stage2Parsed(BaseModel):
    """Stage 2 fields: primary anchor page from Stage 1 candidates."""

    question: str
    rewritten_query: Optional[str] = None

    anchor_page_id: Optional[str] = None
    anchor_selected: bool = False
    anchor_id_valid: bool = False
    selection_method: Optional[str] = None
    selection_path: Optional[str] = None
    workflow_completed: bool = False
    workflow_error: Optional[str] = None

    candidate_page_ids: list[str] = Field(default_factory=list)
    anchor_in_candidates: bool = False
    anchor_page_content: str = ""

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


def _is_valid_page_id(page_id: str | None) -> bool:
    """KB page ids in this agent are numeric strings (e.g. '8194')."""
    return bool(page_id) and str(page_id).strip().isdigit()


def _collect_candidate_page_ids(agent_output: dict[str, Any]) -> list[str]:
    """Best-effort candidates from context / answer (offline; no MCP)."""
    found: list[str] = []
    blobs = list(adk_parser.extract_context(agent_output)) + [adk_parser.extract_answer(agent_output)]
    for blob in blobs:
        for match in _PAGE_ID_RE.finditer(blob or ""):
            found.append(match.group(1))
        for match in _HEADING_ID_RE.finditer(blob or ""):
            found.append(match.group(1))
    # preserve order, unique
    seen: set[str] = set()
    ordered: list[str] = []
    for pid in found:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return ordered


def _extract_anchor_content(agent_output: dict[str, Any], anchor_page_id: str | None) -> str:
    # Prefer full context blobs that mention this page id
    if anchor_page_id:
        for ctx in adk_parser.extract_context(agent_output):
            if f"page_id: {anchor_page_id}" in ctx or f"page_id:{anchor_page_id}" in ctx:
                return ctx
            if f"#### {anchor_page_id} |" in ctx:
                return ctx

    # Then validation-node output when it looks complete (not truncated with ...)
    best = ""
    for event in adk_parser.extract_events(agent_output):
        output = event.get("output") or {}
        content = output.get("anchor_page_content")
        if isinstance(content, str) and len(content.strip()) > len(best):
            best = content.strip()
    if best and not best.endswith("..."):
        return best
    if best:
        return best

    return adk_parser.extract_answer(agent_output) or ""


def parse(raw: dict[str, Any]) -> Stage2Parsed:
    """Raw captured trace → Stage2Parsed."""
    test_case = raw.get("test_case", {})
    agent_output = raw.get("raw_output", {})

    question = test_case.get("input", {}).get("question", "") or agent_output.get("question", "")
    rewritten_query = adk_parser.state_after(agent_output, "rewritten_query")
    if not isinstance(rewritten_query, str):
        rewritten_query = None

    anchor_event = _find_event_by_path_contains(agent_output, "anchor_node_workflow")
    # Prefer the selection node (baseline / other method)
    baseline_event = _find_event_by_path_contains(agent_output, "anchor_baseline")
    selection_event = baseline_event or anchor_event

    selection_path = None
    if selection_event:
        selection_path = (selection_event.get("nodeInfo") or {}).get("path")

    msg = _event_text(selection_event)
    msg_match = _ANCHOR_MSG_RE.search(msg)
    selection_method = msg_match.group("method").strip() if msg_match else None
    if selection_method:
        selection_method = selection_method.strip()

    state_anchor = adk_parser.state_after(agent_output, "anchor_page_id")
    msg_anchor = msg_match.group("anchor_page_id") if msg_match else None
    anchor_page_id = None
    for candidate in (state_anchor, msg_anchor):
        if candidate is not None and str(candidate).strip():
            anchor_page_id = str(candidate).strip()
            break

    candidates = _collect_candidate_page_ids(agent_output)
    # If search only exposed a count, still allow membership when content lists the page
    anchor_in_candidates = bool(anchor_page_id) and (
        anchor_page_id in candidates or (not candidates and bool(anchor_page_id))
    )
    # Strict when we found any candidates from context
    if candidates:
        anchor_in_candidates = anchor_page_id in candidates

    error = None
    text_lower = msg.lower()
    if "error" in text_lower or "failed" in text_lower:
        error = msg.strip() or "anchor workflow reported an error"

    workflow_completed = selection_event is not None and error is None and bool(anchor_page_id)

    return Stage2Parsed(
        question=question,
        rewritten_query=rewritten_query,
        anchor_page_id=anchor_page_id,
        anchor_selected=bool(anchor_page_id),
        anchor_id_valid=_is_valid_page_id(anchor_page_id),
        selection_method=selection_method,
        selection_path=selection_path,
        workflow_completed=workflow_completed,
        workflow_error=error,
        candidate_page_ids=candidates,
        anchor_in_candidates=anchor_in_candidates,
        anchor_page_content=_extract_anchor_content(agent_output, anchor_page_id),
        answer=adk_parser.extract_answer(agent_output),
        context=adk_parser.extract_context(agent_output),
        events=adk_parser.extract_events(agent_output),
        session_id=adk_parser.extract_session_id(agent_output),
        latency_ms=adk_parser.extract_latency_ms(agent_output),
    )
