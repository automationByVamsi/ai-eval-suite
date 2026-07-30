"""
Pegasus data_transformation helpers.

Uses pegasus.utils.data_transformation when installed:
  - get_required_columns_for_metric → contract columns
  - format_rag_data → standardize DataFrame column names

Falls back to strategy-provided columns if the package/API is unavailable.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Synonyms → Pegasus standard RAG columns (also what format_rag_data expects).
_QUESTION_ALIASES = ("question", "query", "prompt")
_ANSWER_ALIASES = ("answer", "response", "output", "actual_output")
_CONTEXT_ALIASES = ("retrieved_contexts", "retrieval_context", "contexts", "documents")
_REFERENCE_ALIASES = ("reference_answer", "expected_answer", "ground_truth", "reference")


def required_columns(
    metric_key: str,
    method: str,
    *,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    """
    Columns required for a Pegasus metric/method.

    Prefer library lookup; use fallback when pegasus is missing or lookup fails.
    """
    key = (metric_key or "").strip().lower()
    meth = (method or "pegasus").strip().lower() or "pegasus"
    try:
        from pegasus.utils.data_transformation import (  # type: ignore
            get_required_columns_for_metric,
        )

        cols = get_required_columns_for_metric(key, meth)
        if isinstance(cols, (list, tuple)) and cols:
            return tuple(str(c) for c in cols)
    except Exception:  # noqa: BLE001 — offline / older pegasus / unknown metric
        pass
    return fallback


def fallback_columns(
    required: tuple[str, ...],
    required_by_method: dict[str, tuple[str, ...]],
    method: str,
) -> tuple[str, ...]:
    """Merge always-required + method extras (used when library lookup fails)."""
    out = list(required)
    for extra in required_by_method.get(method, ()) or ():
        if extra not in out:
            out.append(extra)
    return tuple(out)


def rag_dataframe(row: dict[str, Any]) -> pd.DataFrame:
    """
    One-row DataFrame in Pegasus RAG standard column names.

    Tries format_rag_data; on failure returns a plain DataFrame of the row.
    """
    normalized = _normalize_rag_row(row)
    df = pd.DataFrame([normalized])
    try:
        from pegasus.utils.data_transformation import format_rag_data  # type: ignore

        kwargs: dict[str, str] = {}
        q = _pick_column(df, _QUESTION_ALIASES)
        a = _pick_column(df, _ANSWER_ALIASES)
        c = _pick_column(df, _CONTEXT_ALIASES)
        r = _pick_column(df, _REFERENCE_ALIASES)
        if q:
            kwargs["question_col"] = q
        if a:
            kwargs["answer_col"] = a
        if c:
            kwargs["retrieved_contexts_col"] = c
        if r:
            kwargs["reference_answer_col"] = r
        if kwargs:
            return format_rag_data(df, **kwargs)
    except Exception:  # noqa: BLE001
        pass
    return df


def parse_score(value: Any) -> float | None:
    """Parse a numeric or free-text score to 0–1 when possible."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        from pegasus.utils.data_transformation import (  # type: ignore
            parse_score_from_response,
        )

        parsed = parse_score_from_response(text)
        if parsed is None:
            return None
        return float(parsed)
    except Exception:  # noqa: BLE001
        return None


def _normalize_rag_row(row: dict[str, Any]) -> dict[str, Any]:
    """Promote common aliases onto standard names before format_rag_data."""
    out = dict(row)
    _ensure_standard(out, "question", _QUESTION_ALIASES)
    _ensure_standard(out, "answer", _ANSWER_ALIASES)
    _ensure_standard(out, "retrieved_contexts", _CONTEXT_ALIASES)
    _ensure_standard(out, "reference_answer", _REFERENCE_ALIASES)
    return out


def _ensure_standard(row: dict[str, Any], standard: str, aliases: tuple[str, ...]) -> None:
    if standard in row and _present(row.get(standard)):
        return
    for alias in aliases:
        if alias == standard:
            continue
        if alias in row and _present(row.get(alias)):
            row[standard] = row[alias]
            return


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return bool(value)
    return bool(str(value).strip())


def _pick_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    cols = set(df.columns)
    for name in aliases:
        if name in cols:
            return name
    return None
