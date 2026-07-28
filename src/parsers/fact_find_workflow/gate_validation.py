"""
Gate validation — complaint reference format / InvalidComplaintId path.

A valid complaint reference is NC + 8 digits with no surrounding text.
Failed validation sets stateDelta.complaint_validation_failed and returns
an InvalidComplaintId message. Successful validation proceeds to data gather.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.parsers import adk_parser

_COMPLAINT_REF_RE = re.compile(r"^NC\d{8}$")
_INVALID_MARKERS = ("InvalidComplaintId", "valid complaint reference must begin")


class GateValidationParsed(BaseModel):
    """Structured view of the complaint-reference validation stage."""
    complaint_ref: str
    validation_failed: bool
    successful_run: Optional[bool] = None
    initialized: Optional[bool] = None
    interaction_count: Optional[int] = None
    answer: str = ""
    is_invalid_complaint_message: bool = False
    looks_like_summary: bool = False
    context: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    latency_ms: Optional[float] = None


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


# Back-compat alias used by other parsers in this package.
_state_value = state_value


def parse(raw: dict[str, Any]) -> GateValidationParsed:
    """Extract validation-stage signals from a saved Fact Find run."""
    test_case = raw.get("test_case", {})
    agent_output = raw.get("raw_output", {})
    complaint_ref = (
        test_case.get("input", {}).get("complaint_ref")
        or agent_output.get("complaintRef")
        or ""
    )
    answer = adk_parser.extract_answer(agent_output)
    validation_failed = bool(state_value(agent_output, "complaint_validation_failed"))
    successful_run = state_value(agent_output, "successful_run")
    initialized = state_value(agent_output, "initialized")
    interaction_count = state_value(agent_output, "interaction_count")
    is_invalid = any(marker in answer for marker in _INVALID_MARKERS)
    looks_like_summary = "Customer FactFind Summary" in answer or "Complaint Reference:" in answer

    return GateValidationParsed(
        complaint_ref=str(complaint_ref),
        validation_failed=validation_failed,
        successful_run=successful_run if isinstance(successful_run, bool) else None,
        initialized=initialized if isinstance(initialized, bool) else None,
        interaction_count=interaction_count if isinstance(interaction_count, int) else None,
        answer=answer,
        is_invalid_complaint_message=is_invalid,
        looks_like_summary=looks_like_summary,
        context=adk_parser.extract_context(agent_output),
        events=adk_parser.extract_events(agent_output),
        session_id=adk_parser.extract_session_id(agent_output),
        latency_ms=adk_parser.extract_latency_ms(agent_output),
    )


def is_valid_complaint_ref(value: str) -> bool:
    """Return True when the value matches the expected NC######## format."""
    return bool(_COMPLAINT_REF_RE.match((value or "").strip()))
