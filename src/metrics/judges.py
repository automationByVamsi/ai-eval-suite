"""
LLM judges: score one metric for one test case.

This file has three parts, top to bottom:

  1. run_judge() + pick_engine()   what every metric goes through: choose the engine, run it,
                                   turn the score into pass / fail / skip / error
  2. score_with_deepeval()         DeepEval: library metrics + custom rubrics (GEval)
  3. score_with_pegasus()          Pegasus: the team's standard RAG metrics

Which engine scores a metric — the whole rule:
  custom rubric / criteria                             -> DeepEval (GEval)
  library metric with `pegasus:` and Pegasus installed -> Pegasus
  otherwise                                            -> DeepEval (with a one-time warning if it
                                                          was meant to be Pegasus)
  `engine: deepeval|pegasus` on a metric in agent.yaml forces one (rarely needed).

Outcomes:
  a needed field is empty for this case -> SKIP  (never a silent pass or fail)
  the judge crashed / timed out         -> ERROR (never a low score)
  otherwise                             -> PASS if score >= threshold, else FAIL

Which metrics exist, their Pegasus / DeepEval class names and the fields they need are in
metric_library.yaml — add or remove metrics there, not here. Both engines use the CORTEX model
(src/clients/cortex_client.py). DeepEval and Pegasus are imported inside their functions: they are
slow to import, and Pegasus may not be installed on every machine.

Used by: src/runners/suite_runner.py.
"""

from __future__ import annotations

import functools
import importlib.util
import os
from typing import Any

from src.clients import cortex_client
from src.core.results import ERROR, FAIL, PASS, SKIP, Result
from src.metrics.library import definition
from src.utils.text import first, is_empty

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")   # no usage data sent from the office network

DEFAULT_THRESHOLD = 0.7


# =============================================================================================
# 1. Every metric: choose the engine, score, decide the outcome
# =============================================================================================

def run_judge(name: str, spec: dict[str, Any], fields: dict[str, Any]) -> Result:
    """
    Score metric `name` (its settings `spec` from agent.yaml) on one case's `fields`.

    Never raises: any problem becomes an ERROR result, so one bad judge can't stop a run.
    """
    metric = definition(name, spec)
    threshold = float(metric.get("threshold", DEFAULT_THRESHOLD))
    # metric.get(f, f): the field the metric reads, re-mapped if agent.yaml says e.g. `answer: rewritten_query`.
    values = {f: fields.get(metric.get(f, f)) for f in metric["needs"]}
    result = Result(name=name, kind="judge", status=SKIP, threshold=threshold)

    missing = [metric.get(f, f) for f, v in values.items() if is_empty(v)]
    if missing:
        result.reason = f"skipped: case has no {', '.join(missing)}"
        return result

    try:
        result.engine = pick_engine(metric)
        if result.engine == "pegasus":
            score, reason = score_with_pegasus(metric, values, threshold)
        else:
            score, reason = score_with_deepeval(name, metric, values, threshold)
    except Exception as exc:  # noqa: BLE001 — surfaced as ERROR, never as a low score
        result.status, result.reason = ERROR, f"{type(exc).__name__}: {exc}"
        return result

    result.score = round(float(score), 4)
    result.status = PASS if result.score >= threshold else FAIL
    result.reason = reason or ""
    return result


def pick_engine(metric: dict[str, Any]) -> str:
    """'pegasus' or 'deepeval' for a metric definition — see the rule at the top of this file."""
    if metric.get("engine"):
        return metric["engine"]
    if metric.get("pegasus") and pegasus_installed():
        return "pegasus"
    if metric.get("deepeval") or metric.get("criteria"):
        if metric.get("pegasus"):
            _warn_once("Pegasus is not installed — Pegasus metrics are running on DeepEval on this machine.")
        return "deepeval"
    raise RuntimeError("this metric only exists in Pegasus, and Pegasus is not installed")


@functools.cache
def pegasus_installed() -> bool:
    """True when the internal pegasus package can be imported on this machine."""
    return importlib.util.find_spec("pegasus") is not None


@functools.cache
def _warn_once(message: str) -> None:
    print(f"WARNING: {message}")


# =============================================================================================
# 2. DeepEval
#    library metric with `deepeval: <Class>`  -> that class from deepeval.metrics
#    custom rubric / criteria                 -> GEval, judging only the fields the metric needs
# =============================================================================================

def score_with_deepeval(name: str, metric: dict[str, Any], values: dict[str, Any],
                        threshold: float) -> tuple[float, str]:
    """(score 0..1, reason) for one case. `values` holds the standard fields the metric needs."""
    import deepeval.metrics as dm
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


# =============================================================================================
# 3. Pegasus (internal package — install it separately, see the README)
#    Library metrics name a class in pegasus.metrics.rag (`pegasus: Faithfulness`). Pegasus can
#    compute a metric three ways; choose per metric in agent.yaml with
#        method: pegasus (default) | ragas | deepeval
# =============================================================================================

def score_with_pegasus(metric: dict[str, Any], values: dict[str, Any], threshold: float) -> tuple[float, str]:
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
    score = first(out.get("score"))
    if score is None:
        raise RuntimeError(f"Pegasus returned no score: {out}")
    # Different Pegasus metrics name their explanation differently.
    reason = first(out.get("reasoning") or out.get("reasons") or out.get("details"))
    return float(score), str(reason or "")
