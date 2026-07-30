"""
Shared Fact Find signals from an ADK trace.

Keep heuristics and stateDelta reads here so view / gate / summary
do not duplicate them.
"""

from __future__ import annotations

from typing import Any

from src.parsers import adk_parser

INVALID_MARKERS = (
    "InvalidComplaintId",
    "valid complaint reference must begin",
)

_SUMMARY_MARKERS = (
    "FactFind Summary",
    "Customer FactFind Summary",
    "Complaint Reference",
    "Complaint Reference:",
)


def state_value(raw: dict[str, Any], key: str) -> Any:
    """Last value written for key, including explicit False/0 (unlike state_after)."""
    value = None
    seen = False
    for event in adk_parser.extract_events(raw):
        delta = event.get("actions", {}).get("stateDelta", {})
        if key in delta:
            value = delta[key]
            seen = True
    return value if seen else None


def unwrap_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Support flat ADK saves and { raw_output: {...} } wrappers."""
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("raw_output")
    if isinstance(inner, dict) and (
        "agentOutput" in inner or "raw_events" in inner or "sessionId" in inner
    ):
        return inner
    return raw


def is_invalid_message(answer: str) -> bool:
    """True when the agent reply looks like InvalidComplaintId / format error."""
    return any(marker in (answer or "") for marker in INVALID_MARKERS)


def looks_like_summary(answer: str) -> bool:
    """True when the agent reply looks like a Customer FactFind Summary."""
    text = answer or ""
    return any(marker in text for marker in _SUMMARY_MARKERS)
