"""
Agent-agnostic: case + AgentResponse → EvalSample → judge-ready response.

Agent packs must enrich first (parsers/<agent>/): fill answer, context,
and any agent metadata. This module only packages shared judge fields.
"""

from __future__ import annotations

from typing import Any

from src.eval.sample import EvalSample
from src.models.agent_response import AgentResponse


def build_sample(case: dict[str, Any], response: AgentResponse) -> EvalSample:
    """
    Map case JSON + enriched response into EvalSample.

    Expects agent enrich to have already placed retrieval chunks on
    response.context (and optional metadata.source_document).
    """
    inp = case.get("input") or {}
    expected = case.get("expected") or {}
    meta = response.metadata or {}

    question = str(
        meta.get("question")
        or inp.get("question")
        or inp.get("complaint_ref")
        or meta.get("complaint_ref")
        or _first_input_string(inp)
        or ""
    )
    reference = str(
        expected.get("expected_answer")
        or expected.get("answer")
        or meta.get("expected_answer")
        or meta.get("reference_answer")
        or ""
    )
    contexts = _unique_texts(
        list(response.context or []),
        meta.get("retrieved_contexts"),
        meta.get("retrieval_context"),
    )
    # Agent enrich must set this when needed (e.g. Fact Find summarization).
    source_document = str(meta.get("source_document") or "")

    return EvalSample(
        question=question,
        answer=response.answer or "",
        retrieved_contexts=contexts,
        reference_answer=reference,
        source_document=source_document,
    )


def attach_sample(response: AgentResponse, sample: EvalSample) -> AgentResponse:
    """Copy EvalSample onto response so DeepEval *_source and Pegasus both work."""
    meta = dict(response.metadata or {})
    meta.update(sample.metadata_aliases())
    return response.model_copy(
        update={
            "answer": sample.answer or response.answer,
            "context": list(sample.retrieved_contexts),
            "metadata": meta,
        }
    )


def prepare_sample(
    case: dict[str, Any],
    response: AgentResponse,
) -> AgentResponse:
    """
    Build EvalSample from case + response and attach judge aliases.

    Call after parsers/<agent>.enrich(...).
    """
    sample = build_sample(case, response)
    return attach_sample(response, sample)


def _first_input_string(inp: dict[str, Any]) -> str:
    """Scaffolded agents may use an arbitrary message field as the prompt."""
    for value in inp.values():
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _unique_texts(*groups: Any) -> list[str]:
    """Flatten string groups and keep order without duplicates."""
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if group is None:
            continue
        items = group if isinstance(group, list) else [group]
        for item in items:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out
