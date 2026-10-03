"""
LLM judges: score one metric for one test case.

This file has three parts, top to bottom:

  1. run_judge() + pick_engine()   what every metric goes through: choose the engine, run it,
                                   turn the score into pass / fail / skip / error
  2. score_with_deepeval()         DeepEval: library metrics + custom rubrics (GEval)
  3. score_with_pegasus()          Pegasus: the team's standard RAG metrics

Which engine scores a metric — the whole rule:
  custom rubric / criteria                             -> DeepEval (GEval)
  library metric with `pegasus:`, Pegasus installed
    and CORTEX credentials Pegasus can use             -> Pegasus
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
import json
import math
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

    if score is None or math.isnan(float(score)):
        # Pegasus returns NaN instead of raising when its LLM call failed: that's an ERROR, not a FAIL.
        result.status = ERROR
        result.reason = f"no score (the judge's LLM call failed — see the log above) {reason or ''}".strip()
        return result
    result.score = round(float(score), 4)
    result.status = PASS if result.score >= threshold else FAIL
    result.reason = reason or ""
    return result


def pick_engine(metric: dict[str, Any]) -> str:
    """'pegasus' or 'deepeval' for a metric definition — see the rule at the top of this file."""
    if metric.get("engine"):
        return metric["engine"]
    if metric.get("pegasus") and pegasus_installed() and pegasus_has_credentials():
        return "pegasus"
    if metric.get("deepeval") or metric.get("criteria"):
        if metric.get("pegasus") and not pegasus_installed():
            _warn_once("Pegasus is not installed — Pegasus metrics are running on DeepEval on this machine.")
        elif metric.get("pegasus"):
            _warn_once("Pegasus has no CORTEX credentials (CORTEX_API_KEY, or CORTEX_CLIENT_ID + "
                       "CORTEX_CLIENT_SECRET, or CORTEX_AUTH=devkit) — Pegasus metrics are running on DeepEval.")
        return "deepeval"
    raise RuntimeError("this metric only exists in Pegasus, and Pegasus is not installed or has no credentials")


def pegasus_has_credentials() -> bool:
    """Pegasus signs its own CORTEX calls: an API key / client id + secret, or the DevKit sign-in."""
    return cortex_client.pegasus_can_authenticate()


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
        input=_as_text(values.get("question")),
        actual_output=_as_text(values.get("answer")),
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
#    Library metrics name a class in pegasus.metrics.rag (`pegasus: Faithfulness`), or in another
#    module with `module:` (e.g. agentic). Pegasus can compute a RAG metric three ways; choose per
#    metric in agent.yaml with
#        method: pegasus (default) | ragas | deepeval
# =============================================================================================

def score_with_pegasus(metric: dict[str, Any], values: dict[str, Any], threshold: float) -> tuple[float, str]:
    """
    (score 0..1, reason) for one case — called the same way as the Knowledge Agent's own Pegasus
    guardrails: a one-row DataFrame, Metric(llm=..., method=...).evaluate(frame)["score"].
    The threshold is applied by run_judge, not by Pegasus.

    RAG metrics (pegasus.metrics.rag) get the columns question / answer / retrieved_contexts /
    reference_answer. A metric from another module names its own columns in metric_library.yaml
    (`columns:`), e.g. ResponseAlignment: query / agent_response / background.
    """
    import importlib

    import pandas as pd

    module_name = metric.get("module", "rag")
    if metric.get("columns"):
        given = {**values, "background": metric.get("background")}
        row = {column: _as_text(given.get(field)) for field, column in metric["columns"].items()
               if not is_empty(given.get(field))}
    else:
        row = {
            "question": _as_text(values.get("question")),
            "answer": _as_text(values.get("answer")),
            "retrieved_contexts": [str(c) for c in values.get("contexts") or []],
        }
        if values.get("expected_answer"):
            row["reference_answer"] = values["expected_answer"]   # correctness / context metrics use it
    frame = pd.DataFrame([row])

    kwargs: dict[str, Any] = {"llm": cortex_client.pegasus_llm(), **(metric.get("options") or {})}
    if module_name == "rag" or "method" in metric:   # only the RAG metrics take method= (pegasus|ragas|deepeval)
        kwargs["method"] = metric.get("method", "pegasus")
    judge_class = getattr(importlib.import_module(f"pegasus.metrics.{module_name}"), metric["pegasus"])
    out = judge_class(**kwargs).evaluate(frame)
    score = first(out["score"])
    if score is None or pd.isna(score):
        raise RuntimeError(f"Pegasus returned no numeric score: {out}")
    # Different Pegasus metrics name their explanation differently.
    reason = next((first(out[k]) for k in ("reasoning", "reasons", "reason", "explanation", "score_details",
                                            "details") if _has(out, k)), "")
    return float(score), str(reason or "")


def _as_text(value: Any) -> str:
    """Judges get text: a JSON value (e.g. the agent's whole structured output) as indented JSON."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return str(value)


def _has(out: Any, key: str) -> bool:
    try:
        return key in out
    except TypeError:
        return False
