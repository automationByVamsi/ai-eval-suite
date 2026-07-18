"""Typed, stage-specific shape of a parsed knowledge_agent trace. One class per stage."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Stage1Trace(BaseModel):
    """Stage 1 = query rewrite: did the agent rewrite the user's question, and was it carried into state?"""

    question: str
    rewrite_ran: bool
    rewritten_query: Optional[str] = None
    carried_into_state: bool
    answer: str = ""
    context: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    latency_ms: Optional[float] = None
