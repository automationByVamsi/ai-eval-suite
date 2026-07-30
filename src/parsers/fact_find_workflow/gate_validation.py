"""
Gate validation — complaint reference format / InvalidComplaintId path.

Builds on FactFindView (extract once); adds GateValidationParsed for suites
that still want the dedicated gate shape.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.parsers import adk_parser
from src.parsers.fact_find_workflow.signals import state_value, unwrap_raw
from src.parsers.fact_find_workflow.view import extract

# Re-export for older imports: from ...gate_validation import state_value
__all__ = [
    "GateValidationParsed",
    "state_value",
    "parse",
    "is_valid_complaint_ref",
]

_COMPLAINT_REF_RE = re.compile(r"^NC\d{8}$")


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


def parse(raw: dict[str, Any]) -> GateValidationParsed:
    """Extract validation-stage signals from a saved Fact Find run."""
    test_case = raw.get("test_case", {}) if isinstance(raw.get("test_case"), dict) else {}
    complaint_ref = str((test_case.get("input") or {}).get("complaint_ref") or "")

    view = extract(raw, complaint_ref=complaint_ref)
    flat = unwrap_raw(raw)

    return GateValidationParsed(
        complaint_ref=view.complaint_ref or complaint_ref,
        validation_failed=view.validation_failed,
        successful_run=view.successful_run,
        initialized=view.initialized,
        interaction_count=view.interaction_count,
        answer=view.answer,
        is_invalid_complaint_message=view.is_invalid_message,
        looks_like_summary=view.looks_like_summary,
        context=adk_parser.extract_context(flat),
        events=adk_parser.extract_events(flat),
        session_id=view.session_id,
        latency_ms=adk_parser.extract_latency_ms(flat),
    )


def is_valid_complaint_ref(value: str) -> bool:
    """Return True when the value matches the expected NC######## format."""
    return bool(_COMPLAINT_REF_RE.match((value or "").strip()))
