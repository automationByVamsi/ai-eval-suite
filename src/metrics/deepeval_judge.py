"""
Score a metric with DeepEval, using the CORTEX model as the judge.

  library metric with `deepeval: <Class>`   -> that class from deepeval.metrics
  custom rubric / criteria                  -> GEval, judging only the fields the metric needs

Used by: metrics/judge.py.
"""

from __future__ import annotations

from typing import Any

from src.clients import cortex_client


def score(name: str, metric: dict[str, Any], values: dict[str, Any], threshold: float) -> tuple[float, str]:
    """(score 0..1, reason) for one case. `values` holds the standard fields the metric needs."""
    import deepeval.metrics as dm  # imported here: DeepEval is slow to import
    from deepeval.test_case import LLMTestCase

    llm = cortex_client.deepeval_llm()
    if metric.get("criteria") and not metric.get("deepeval"):
        judge = dm.GEval(name=name, criteria=metric["criteria"],
                         evaluation_params=[_geval_param(f) for f in values],
                         model=llm, threshold=threshold, async_mode=False)
    else:
        judge = getattr(dm, metric["deepeval"])(model=llm, threshold=threshold, async_mode=False)

    contexts = values.get("contexts")
    judge.measure(LLMTestCase(
        input=str(values.get("question") or ""),
        actual_output=str(values.get("answer") or ""),
        expected_output=values.get("expected_answer") or None,
        retrieval_context=[str(c) for c in contexts] if contexts else None,
    ))
    return judge.score or 0.0, judge.reason or ""


def _geval_param(field_name: str) -> Any:
    """Our field name -> DeepEval's test-case parameter (the enum was renamed in DeepEval 4)."""
    try:
        from deepeval.test_case import SingleTurnParams as P
    except ImportError:  # deepeval < 4
        from deepeval.test_case import LLMTestCaseParams as P
    return {
        "question": P.INPUT,
        "answer": P.ACTUAL_OUTPUT,
        "contexts": P.RETRIEVAL_CONTEXT,
        "expected_answer": P.EXPECTED_OUTPUT,
    }[field_name]
