"""
Score one metric for one test case.

Which engine scores a metric — the whole rule:
  custom rubric / criteria                            -> DeepEval (GEval)
  library metric with `pegasus:` and Pegasus installed -> Pegasus
  otherwise                                           -> DeepEval (with a one-time warning if it
                                                         was meant to be Pegasus)
  `engine: deepeval|pegasus` on a metric in agent.yaml forces one (rarely needed).

Outcomes:
  a needed field is empty for this case -> SKIP (never a silent pass or fail)
  the judge crashed / timed out         -> ERROR (never a low score)
  otherwise                             -> PASS if score >= threshold, else FAIL
"""

from __future__ import annotations

import functools
import os
from typing import Any

from src.core.results import ERROR, FAIL, PASS, SKIP, Result
from src.metrics import deepeval_judge, pegasus_judge
from src.metrics.library import definition
from src.utils.text import is_empty

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")   # no usage data sent from the office network

DEFAULT_THRESHOLD = 0.7


def run_judge(name: str, spec: dict[str, Any], fields: dict[str, Any]) -> Result:
    """
    Score metric `name` (settings `spec` from agent.yaml) on one case's `fields`.

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
            score, reason = pegasus_judge.score(metric, values, threshold)
        else:
            score, reason = deepeval_judge.score(name, metric, values, threshold)
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
    if metric.get("pegasus") and pegasus_judge.is_installed():
        return "pegasus"
    if metric.get("deepeval") or metric.get("criteria"):
        if metric.get("pegasus"):
            _warn_once("Pegasus is not installed — Pegasus metrics are running on DeepEval on this machine.")
        return "deepeval"
    raise RuntimeError("this metric only exists in Pegasus, and Pegasus is not installed")


@functools.cache
def _warn_once(message: str) -> None:
    print(f"WARNING: {message}")
