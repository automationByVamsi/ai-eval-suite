"""Resolve case/response fields into Pegasus DataFrame columns + contracts."""

from __future__ import annotations

from typing import Any

from src.core.exceptions import MetricContractError
from src.metrics.base_metric import resolve_field
from src.models.agent_response import AgentResponse
from src.models.test_case import TestCase


def build_row(
    field_names: tuple[str, ...],
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
) -> dict[str, Any]:
    """Build a Pegasus row dict for the requested column names."""
    builders = {
        "question": lambda: _question(cfg, test_case, response),
        "answer": lambda: _answer(cfg, test_case, response),
        "reference_answer": lambda: _reference(cfg, test_case, response),
        "retrieved_contexts": lambda: _contexts(cfg, test_case, response),
    }
    row: dict[str, Any] = {}
    for name in field_names:
        if name not in builders:
            raise ValueError(f"Unknown Pegasus field: {name}")
        row[name] = builders[name]()
    return row


def require_fields(case_id: str, metric: str, fields: dict[str, Any]) -> None:
    """Raise MetricContractError if any required field is empty."""
    missing: list[str] = []
    for key, value in fields.items():
        if isinstance(value, list):
            if not value:
                missing.append(key)
        elif not str(value or "").strip():
            missing.append(key)
    if missing:
        raise MetricContractError(case_id=case_id, metric=metric, missing=missing)


def _question(cfg: dict[str, Any], test_case: TestCase, response: AgentResponse) -> str:
    return str(
        resolve_field(cfg.get("input_source") or "question", test_case, response) or ""
    ).strip()


def _answer(cfg: dict[str, Any], test_case: TestCase, response: AgentResponse) -> str:
    return str(
        resolve_field(cfg.get("actual_source") or "answer", test_case, response) or ""
    ).strip()


def _reference(cfg: dict[str, Any], test_case: TestCase, response: AgentResponse) -> str:
    reference = resolve_field(
        cfg.get("expected_source") or "expected_answer", test_case, response
    )
    if not reference:
        reference = (response.metadata or {}).get("reference_answer") or (
            response.metadata or {}
        ).get("expected_answer")
    return str(reference or "").strip()


def _contexts(
    cfg: dict[str, Any], test_case: TestCase, response: AgentResponse
) -> list[str]:
    contexts = resolve_field(
        cfg.get("context_source") or "retrieval_context", test_case, response
    )
    if not isinstance(contexts, list) or not contexts:
        contexts = (response.metadata or {}).get("retrieved_contexts")
    if not isinstance(contexts, list):
        return []
    return [str(c).strip() for c in contexts if str(c).strip()]
