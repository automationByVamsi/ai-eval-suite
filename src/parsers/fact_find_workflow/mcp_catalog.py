"""
Fact Find MCP catalog + extraction helpers for DeepEval MCP metrics.

MCPUseMetric needs:
  - mcp_servers: available tool catalog
  - mcp_tools_called (or tools_called): what the agent actually invoked

MCPTaskCompletionMetric needs ConversationalTestCase; we adapt a single-turn
Fact Find run into a 2-turn conversation (user complaint_ref → assistant summary).
"""

from __future__ import annotations

from typing import Any

from deepeval.test_case import ToolCall
from deepeval.test_case.mcp import MCPServer, MCPToolCall

from src.parsers import adk_parser

# Default MCP tool surface for Fact Find (mirrors backend services / agent tools).
FACTFIND_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_ica_case_details",
        "description": "Fetch ICA case details for a complaint reference (NC########).",
        "input_schema": {"complaintRef": "string"},
    },
    {
        "name": "get_account_details",
        "description": "Fetch Counter account details for a full account number.",
        "input_schema": {"accountNumber": "string"},
    },
    {
        "name": "get_customer_holding",
        "description": "Fetch customer holding summary for a party ID (criterion=ALL).",
        "input_schema": {"partyId": "string", "criterion": "ALL"},
    },
    {
        "name": "get_contact_notes",
        "description": "Fetch OCIS contact notes for a party ID.",
        "input_schema": {"partyId": "string"},
    },
    {
        "name": "get_trusted_parties",
        "description": "Fetch OCIS trusted parties for a party ID.",
        "input_schema": {"partyId": "string"},
    },
]


def default_factfind_mcp_servers() -> list[MCPServer]:
    return [
        MCPServer(
            server_name="fact_find_backends",
            transport="streamable-http",
            available_tools=list(FACTFIND_MCP_TOOLS),
        )
    ]


def extract_mcp_tools_called(raw: dict[str, Any]) -> list[MCPToolCall]:
    """
    Pair ADK functionCall (+ optional functionResponse) into MCPToolCall objects.
    Falls back to call-only entries when no response is present.
    """
    calls: list[MCPToolCall] = []
    pending: dict[str, dict[str, Any]] = {}

    for event in adk_parser.extract_events(raw):
        for part in (event.get("content") or {}).get("parts") or []:
            call = part.get("functionCall") or part.get("function_call")
            if isinstance(call, dict) and call.get("name"):
                name = str(call["name"])
                args = call.get("args") or call.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {"raw": args}
                call_id = str(call.get("id") or name)
                pending[call_id] = {"name": name, "args": args}
                # Also index by name for responses that only echo the tool name.
                pending[f"name:{name}"] = pending[call_id]

            resp = part.get("functionResponse") or part.get("function_response")
            if isinstance(resp, dict) and (resp.get("name") or resp.get("id")):
                key = str(resp.get("id") or "")
                meta = pending.get(key) or pending.get(f"name:{resp.get('name')}")
                if not meta:
                    meta = {
                        "name": str(resp.get("name") or "unknown"),
                        "args": {},
                    }
                result = resp.get("response") or resp.get("result") or resp
                calls.append(
                    MCPToolCall(name=meta["name"], args=meta["args"], result=result)
                )
                continue

    # Calls without a matched response
    seen_names = {c.name for c in calls}
    for meta in pending.values():
        name = meta["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        calls.append(MCPToolCall(name=name, args=meta["args"], result={}))

    return calls


def mcp_tools_from_tool_calls(tools: list[ToolCall] | None) -> list[MCPToolCall]:
    """Convert DeepEval ToolCall list into MCPToolCall list."""
    out: list[MCPToolCall] = []
    for tool in tools or []:
        args = tool.input_parameters if isinstance(tool.input_parameters, dict) else {}
        out.append(MCPToolCall(name=tool.name, args=args, result=tool.output or {}))
    return out
