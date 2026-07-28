"""
Fact Find–only helpers: attach aggregated-payload context for judges.

Shared judge scoring stays in src.runners.evaluate.evaluate(...).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.agent_response import AgentResponse
from src.parsers.fact_find_workflow.aggregated_payload import (
    load_aggregated_payload,
    payload_to_context,
)


def prepare_for_judges(
    case: dict[str, Any],
    response: AgentResponse,
    *,
    repo_root: str | Path = ".",
) -> AgentResponse:
    """
    If case.expected.aggregated_payload_path is set, load ground truth and
    put it on response.context (+ metadata.source_document) for suite judges.

    Invalid-ref cases have no payload path — response is returned unchanged.
    """
    expected = case.get("expected") or {}
    rel = expected.get("aggregated_payload_path")
    if not rel:
        return response

    path = Path(repo_root) / str(rel)
    if not path.is_file():
        raise FileNotFoundError(f"Aggregated payload not found: {path}")

    payload = load_aggregated_payload(path)
    chunks = payload_to_context(payload)
    source_document = "\n\n".join(chunks)

    meta = dict(response.metadata or {})
    meta["source_document"] = source_document
    meta["retrieval_context"] = chunks
    meta["ground_truth_context"] = chunks

    return response.model_copy(update={"context": chunks, "metadata": meta})
