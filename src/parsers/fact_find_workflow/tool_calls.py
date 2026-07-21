"""
Extract tool / MCP calls from an ADK event stream for DeepEval ToolCorrectness.

Looks for common ADK shapes:
  content.parts[].functionCall / function_call
  content.parts[].functionResponse / function_response
"""

from __future__ import annotations

from typing import Any

from deepeval.test_case import ToolCall

from src.agents import adk_parser


def extract_tools_called(raw: dict[str, Any]) -> list[ToolCall]:
    """Unique tool names invoked during the run (order preserved)."""
    seen: set[str] = set()
    tools: list[ToolCall] = []
    for event in adk_parser.extract_events(raw):
        for part in (event.get("content") or {}).get("parts") or []:
            call = part.get("functionCall") or part.get("function_call") or {}
            name = call.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            args = call.get("args") or call.get("arguments") or {}
            tools.append(
                ToolCall(
                    name=str(name),
                    input_parameters=args if isinstance(args, dict) else {"raw": args},
                )
            )
    return tools


def tool_calls_from_expected(names: list[str] | None) -> list[ToolCall]:
    return [ToolCall(name=str(n)) for n in (names or []) if n]
