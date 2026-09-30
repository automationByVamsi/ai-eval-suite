"""
Score a metric with Pegasus (internal package; install it separately — see the README).

Library metrics name a class in pegasus.metrics.rag (`pegasus: Faithfulness`). Pegasus itself
can compute a metric three ways; pick one per metric in agent.yaml with `method:`
    method: pegasus (default) | ragas | deepeval

Used by: metrics/judge.py.
"""

from __future__ import annotations

import functools
import importlib.util
from typing import Any

from src.clients import cortex_client
from src.utils.text import first


@functools.cache
def is_installed() -> bool:
    """True when the pegasus package can be imported on this machine."""
    return importlib.util.find_spec("pegasus") is not None


def score(metric: dict[str, Any], values: dict[str, Any], threshold: float) -> tuple[float, str]:
    """(score 0..1, reason) for one case, from a one-row DataFrame in Pegasus' RAG column format."""
    import pandas as pd
    from pegasus.metrics import rag

    frame = pd.DataFrame([{
        "question": values.get("question") or "",
        "answer": values.get("answer") or "",
        "retrieved_contexts": list(values.get("contexts") or []),
        "reference_answer": values.get("expected_answer") or "",
    }])
    try:  # Pegasus' own column normaliser, when this Pegasus version has it
        from pegasus.utils.data_transformation import format_rag_data
        frame = format_rag_data(frame, question_col="question", answer_col="answer",
                                retrieved_contexts_col="retrieved_contexts",
                                reference_answer_col="reference_answer")
    except (ImportError, TypeError):
        pass

    judge = getattr(rag, metric["pegasus"])(llm=cortex_client.pegasus_llm(),
                                            method=metric.get("method", "pegasus"), threshold=threshold)
    out = judge.evaluate(frame)
    value = first(out.get("score"))
    if value is None:
        raise RuntimeError(f"Pegasus returned no score: {out}")
    # Different Pegasus metrics name their explanation differently.
    reason = first(out.get("reasoning") or out.get("reasons") or out.get("details"))
    return float(value), str(reason or "")
