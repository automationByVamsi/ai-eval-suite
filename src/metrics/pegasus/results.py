"""Map Pegasus evaluate() dict → MetricResult."""

from __future__ import annotations

from typing import Any

from src.metrics.pegasus.columns import parse_score
from src.models.metric_result import MetricResult


def result_from_pegasus(
    name: str, threshold: float, results: dict[str, Any]
) -> MetricResult:
    score = parse_score(results.get("score"))
    if score is None:
        score = 0.0
    passed = bool(results.get("passed", score >= threshold))
    reason = _reason_from_pegasus_results(results)
    if not reason or _is_score_only_reason(reason):
        if passed:
            reason = f"{reason + ' — ' if reason else ''}score {score:.2f} ≥ threshold {threshold:.2f}"
        else:
            reason = (
                f"{reason + ' — ' if reason else ''}"
                f"score {score:.2f} < threshold {threshold:.2f}"
            )
    return MetricResult(
        name=name,
        score=score,
        threshold=threshold,
        passed=passed,
        reason=reason.strip(),
    )


def _reason_from_pegasus_results(results: dict[str, Any]) -> str:
    for key in ("reasoning", "reasons"):
        value = results.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if first and str(first).strip():
                return str(first).strip()
        elif isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("details", "score_details"):
        value = results.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _is_score_only_reason(text: str) -> bool:
    lowered = text.strip().lower()
    return (
        "score:" in lowered
        and "because" not in lowered
        and "reason" not in lowered
        and len(lowered) < 80
    )
