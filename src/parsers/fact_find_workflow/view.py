"""
Fact Find parser — simple fields from a full ADK save.

Shape we expect (see ff_org_adk.json):
  agentOutput, complaintRef, sessionId, raw_events[]
  events may include functionCall / functionResponse (tools).

Usage:
  from src.parsers.fact_find_workflow import extract, enrich

  view = extract(raw_adk_json)
  assert view.complaint_ref == "NC10010556"
  assert "getCustomerSummary" in view.tool_names

  response = enrich(live_response, complaint_ref="NC10010556")
  # → response.metadata ready for judges (complaint_ref, tools_called, …)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deepeval.test_case import ToolCall
from deepeval.test_case.mcp import MCPToolCall

from src.models.agent_response import AgentResponse
from src.parsers import adk_parser
from src.parsers.fact_find_workflow.gate_validation import state_value
from src.parsers.fact_find_workflow.mcp_catalog import extract_mcp_tools_called
from src.parsers.fact_find_workflow.tool_calls import extract_tools_called

_INVALID = ("InvalidComplaintId", "valid complaint reference must begin")


@dataclass(frozen=True)
class FactFindView:
    """Plain fields for asserts + LLM judges (not the raw event dump)."""

    answer: str = ""
    complaint_ref: str = ""
    validation_failed: bool = False
    successful_run: bool | None = None
    looks_like_summary: bool = False
    is_invalid_message: bool = False
    # Tools from functionCall events (empty on slim/replay traces)
    tool_names: tuple[str, ...] = ()
    tools_called: tuple[ToolCall, ...] = field(default_factory=tuple)
    mcp_tools_called: tuple[MCPToolCall, ...] = field(default_factory=tuple)
    # Handy ids from state / tool args when present
    party_id: str = ""
    account_number: str = ""
    session_id: str | None = None


def _unwrap(raw: dict[str, Any]) -> dict[str, Any]:
    """Support flat saves and { raw_output: {...} } wrappers."""
    inner = raw.get("raw_output")
    if isinstance(inner, dict) and (
        "agentOutput" in inner or "raw_events" in inner or "sessionId" in inner
    ):
        return inner
    return raw


def _party_id_from_tools(tools: list[ToolCall]) -> str:
    for tool in tools:
        args = tool.input_parameters or {}
        if isinstance(args, dict) and args.get("partyId"):
            return str(args["partyId"])
    return ""


def extract(raw: dict[str, Any], *, complaint_ref: str = "") -> FactFindView:
    """Read one ADK JSON (live or cached) → FactFindView."""
    raw = _unwrap(raw)
    answer = adk_parser.extract_answer(raw) or ""

    ref = (
        complaint_ref
        or str(raw.get("complaintRef") or "")
        or str(state_value(raw, "complaint_id") or "")
        or ""
    )

    tools = extract_tools_called(raw)
    mcp_tools = extract_mcp_tools_called(raw)
    successful = state_value(raw, "successful_run")

    return FactFindView(
        answer=answer,
        complaint_ref=str(ref),
        validation_failed=bool(state_value(raw, "complaint_validation_failed")),
        successful_run=successful if isinstance(successful, bool) else None,
        looks_like_summary="FactFind Summary" in answer or "Complaint Reference" in answer,
        is_invalid_message=any(m in answer for m in _INVALID),
        tool_names=tuple(t.name for t in tools),
        tools_called=tuple(tools),
        mcp_tools_called=tuple(mcp_tools),
        party_id=_party_id_from_tools(tools),
        account_number=str(state_value(raw, "account_number") or ""),
        session_id=adk_parser.extract_session_id(raw),
    )


def enrich(response: AgentResponse, *, complaint_ref: str = "") -> AgentResponse:
    """
    Put FactFindView fields on response.metadata for catalog *_source.

    After this, judges can resolve complaint_ref / tools_called / answer.
    For summary-vs-aggregate ground truth, still call prepare_for_judges(...).
    """
    raw = response.raw_output if isinstance(response.raw_output, dict) else {}
    view = extract(raw, complaint_ref=complaint_ref)

    meta = dict(response.metadata or {})
    meta.update(
        {
            "complaint_ref": complaint_ref or view.complaint_ref,
            "validation_failed": view.validation_failed,
            "successful_run": view.successful_run,
            "looks_like_summary": view.looks_like_summary,
            "is_invalid_complaint_message": view.is_invalid_message,
            "tool_names": list(view.tool_names),
            "tools_called": list(view.tools_called),
            "mcp_tools_called": list(view.mcp_tools_called),
            "party_id": view.party_id,
            "account_number": view.account_number,
        }
    )

    return response.model_copy(
        update={
            "answer": response.answer or view.answer,
            "metadata": meta,
        }
    )
