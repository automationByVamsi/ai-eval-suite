"""Shared helpers for turning eval results into CheckObservation rows."""

from __future__ import annotations

from typing import Any

from src.verdict.models import CheckObservation


def from_deterministic(results: list[Any]) -> list[CheckObservation]:
    return [
        CheckObservation(name=r.name, kind="deterministic", passed=r.passed, reason=r.reason or "")
        for r in results
    ]


def from_judges(results: list[Any]) -> list[CheckObservation]:
    return [
        CheckObservation(
            name=r.name,
            kind="judge",
            passed=r.passed,
            score=getattr(r, "score", None),
            threshold=getattr(r, "threshold", None),
            reason=getattr(r, "reason", "") or "",
        )
        for r in results
    ]
