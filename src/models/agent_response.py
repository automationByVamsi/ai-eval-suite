"""
AgentResponse is the normalised shape AdkClient (and stage parsers) produce
from a full ADK JSON trace / live /run response.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    answer: str
    raw_output: Any = None
    context: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    latency_ms: Optional[float] = None
