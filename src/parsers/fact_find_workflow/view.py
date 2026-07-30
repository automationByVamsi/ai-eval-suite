"""
Fact Find parser — simple fields from a full ADK save.

Shape we expect (see ff_org_adk.json):
  agentOutput, complaintRef, sessionId, raw_events[]
  events may include functionCall / functionResponse (tools).

Judge path (preferred):
  prepare_response(case, response)  → agent fields + aggregate
  prepare_sample(case, response)    → EvalSample for DeepEval / Pegasus
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepeval.test_case import ToolCall
from deepeval.test_case.mcp import MCPToolCall

from src.models.agent_response import AgentResponse
from src.parsers import adk_parser
from src.parsers.fact_find_workflow.ground_truth import attach_aggregate_context
from src.parsers.fact_find_workflow.mcp_catalog import extract_mcp_tools_called
from src.parsers.fact_find_workflow.signals import (
    is_invalid_message,
    looks_like_summary,
    state_value,
    unwrap_raw,
)
from src.parsers.fact_find_workflow.tool_calls import extract_tools_called


@dataclass(frozen=True)
class FactFindView:
    """Plain fields for asserts + LLM judges (not the raw event dump)."""

    answer: str = ""
    complaint_ref: str = ""
    validation_failed: bool = False
    successful_run: bool | None = None
    looks_like_summary: bool = False
    is_invalid_message: bool = False
    tool_names: tuple[str, ...] = ()
    tools_called: tuple[ToolCall, ...] = field(default_factory=tuple)
    mcp_tools_called: tuple[MCPToolCall, ...] = field(default_factory=tuple)
    party_id: str = ""
    account_number: str = ""
    session_id: str | None = None
    # Extra session flags used by gate_validation.parse
    initialized: bool | None = None
    interaction_count: int | None = None


def _party_id_from_tools(tools: list[ToolCall]) -> str:
    """Return the first party id seen in recorded tool-call arguments."""
    for tool in tools:
        args = tool.input_parameters or {}
        if isinstance(args, dict) and args.get("partyId"):
            return str(args["partyId"])
    return ""


def extract(raw: dict[str, Any], *, complaint_ref: str = "") -> FactFindView:
    """Read one ADK JSON (live, cached, or {raw_output:...} wrap) → FactFindView."""
    raw = unwrap_raw(raw)
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
    initialized = state_value(raw, "initialized")
    interaction_count = state_value(raw, "interaction_count")

    return FactFindView(
        answer=answer,
        complaint_ref=str(ref),
        validation_failed=bool(state_value(raw, "complaint_validation_failed")),
        successful_run=successful if isinstance(successful, bool) else None,
        looks_like_summary=looks_like_summary(answer),
        is_invalid_message=is_invalid_message(answer),
        tool_names=tuple(t.name for t in tools),
        tools_called=tuple(tools),
        mcp_tools_called=tuple(mcp_tools),
        party_id=_party_id_from_tools(tools),
        account_number=str(state_value(raw, "account_number") or ""),
        session_id=adk_parser.extract_session_id(raw),
        initialized=initialized if isinstance(initialized, bool) else None,
        interaction_count=interaction_count if isinstance(interaction_count, int) else None,
    )


def enrich(response: AgentResponse, *, complaint_ref: str = "") -> AgentResponse:
    """
    Put FactFindView fields on response.metadata for catalog *_source.

    Prefer prepare_response(case, response) when you also need aggregate context.
    """
    raw = response.raw_output if isinstance(response.raw_output, dict) else {}
    view = extract(raw, complaint_ref=complaint_ref)

    ref = complaint_ref or view.complaint_ref
    meta = dict(response.metadata or {})
    meta.update(
        {
            "complaint_ref": ref,
            "question": ref,
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


def prepare_response(
    case: dict[str, Any],
    response: AgentResponse,
    *,
    repo_root: str | Path = ".",
) -> AgentResponse:
    """Enrich ADK fields + optional aggregate payload before prepare_sample."""
    complaint_ref = str((case.get("input") or {}).get("complaint_ref") or "")
    response = enrich(response, complaint_ref=complaint_ref)
    return attach_aggregate_context(case, response, repo_root=repo_root)
