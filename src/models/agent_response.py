"""
AgentResponse is the normalised shape every BaseAgent.invoke() (and every
stage parser) must produce, regardless of what the underlying agent looks
like internally.
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
