"""
Knowledge Agent view — named fields for contracts and LLM judges.

Built on src.parsers.adk_parser (shared ADK envelope).
Does not dump raw_events to the judge — only short, stable strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers import adk_parser


@dataclass(frozen=True)
class KnowledgeAgentView:
    """Stable Knowledge Agent fields used by tests and judges."""
    answer: str = ""
    question: str = ""
    rewritten_query: str = ""
    business_area: str = ""
    artifact_id: str = ""
    anchor_page_id: str = ""
    anchor_page_content: str = ""
    decision: str = ""
    session_id: str | None = None
    latency_ms: float | None = None


def _unwrap(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept flat ADK saves or { raw_output: {...} } wrappers."""
    inner = raw.get("raw_output")
    if isinstance(inner, dict) and (
        "agentOutput" in inner or "raw_events" in inner or "sessionId" in inner
    ):
        return inner
    return raw


def extract(raw: dict[str, Any]) -> KnowledgeAgentView:
    """Pull judge/contract-ready fields from a raw ADK dict."""
    raw = _unwrap(raw)

    rewritten = adk_parser.state_after(raw, "rewritten_query") or ""
    if not rewritten:
        event = adk_parser.find_event_by_author(raw, "query_rewrite_agent")
        rewritten = (adk_parser.event_json(event) or {}).get("rewritten_query") or ""

    answer = adk_parser.extract_answer(raw) or ""
    anchor_content = adk_parser.state_after(raw, "anchor_page_content") or ""
    if not anchor_content and "anchor page" in answer.lower():
        anchor_content = answer

    return KnowledgeAgentView(
        answer=answer,
        question=str(adk_parser.state_after(raw, "query") or ""),
        rewritten_query=str(rewritten),
        business_area=str(adk_parser.state_after(raw, "business_area") or ""),
        artifact_id=str(adk_parser.state_after(raw, "artifact_id") or ""),
        anchor_page_id=str(adk_parser.state_after(raw, "anchor_page_id") or ""),
        anchor_page_content=str(anchor_content),
        decision=str(adk_parser.state_after(raw, "decision") or ""),
        session_id=adk_parser.extract_session_id(raw),
        latency_ms=adk_parser.extract_latency_ms(raw),
    )


def enrich(response: AgentResponse, *, question: str = "") -> AgentResponse:
    """
    Copy KA fields onto response.metadata for catalog *_source wiring
    (e.g. actual_source: rewritten_query, anchor_page_content).
    """
    raw = response.raw_output if isinstance(response.raw_output, dict) else {}
    view = extract(raw)

    meta = dict(response.metadata or {})
    meta.update(
        {
            "question": question or view.question or meta.get("question") or "",
            "rewritten_query": view.rewritten_query,
            "business_area": view.business_area,
            "artifact_id": view.artifact_id,
            "anchor_page_id": view.anchor_page_id,
            "anchor_page_content": view.anchor_page_content,
            "decision": view.decision,
        }
    )

    return response.model_copy(
        update={
            "answer": response.answer or view.answer,
            "metadata": meta,
        }
    )
