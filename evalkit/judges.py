"""
LLM-as-a-judge.

Where metrics are defined:
  metric_library.yaml          built-in metrics (relevance, faithfulness, ...) and their engines
  agents/<agent>/agent.yaml    which of them the agent uses + thresholds, and custom `rubric:` judges

Which engine scores a metric — the only rule:
  custom rubric / criteria                           -> DeepEval GEval
  library metric with `pegasus:` + Pegasus installed -> Pegasus
  otherwise                                          -> DeepEval
  (`engine: deepeval|pegasus` on a metric forces one; rarely needed.)

Judges read four standard fields: question, answer, contexts, expected_answer. A metric can
read one of them from another parser field, e.g. `answer: rewritten_query`. If a needed field
is empty for a case, the judge is SKIPPED for that case — never silently passed or failed.
"""

from __future__ import annotations

import functools
import importlib.util
import os
from pathlib import Path
from typing import Any

import yaml

from evalkit.config import ROOT, ConfigError
from evalkit.results import ERROR, FAIL, PASS, SKIP, Result

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

STANDARD_FIELDS = ("question", "answer", "contexts", "expected_answer")
LIBRARY_KEYS = {"needs", "pegasus", "deepeval", "criteria", *STANDARD_FIELDS}
AGENT_KEYS = {"type", "threshold", "rubric", "criteria", "needs", "engine", "method", *STANDARD_FIELDS}


@functools.cache
def library() -> dict[str, dict[str, Any]]:
    """metric_library.yaml, validated."""
    path = ROOT / "metric_library.yaml"
    entries = yaml.safe_load(path.read_text()) or {}
    for name, entry in entries.items():
        where = f"{path.name}: '{name}'"
        if set(entry) - LIBRARY_KEYS:
            raise ConfigError(f"{where} has unknown keys {sorted(set(entry) - LIBRARY_KEYS)}")
        if not entry.get("needs") or set(entry["needs"]) - set(STANDARD_FIELDS):
            raise ConfigError(f"{where} needs `needs:` from {list(STANDARD_FIELDS)}")
        if not (entry.get("pegasus") or entry.get("deepeval") or entry.get("criteria")):
            raise ConfigError(f"{where} needs at least one of pegasus / deepeval / criteria")
    return entries


def definition(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """The full definition of one agent metric: library entry (if any) + the agent's settings."""
    if "rubric" in spec or "criteria" in spec:
        base = {"needs": ["question", "answer"]}
    else:
        base = library()[spec.get("type", name)]
    merged = {**base, **spec}
    if "rubric" in merged:
        merged["criteria"] = Path(merged["rubric"]).read_text().strip()
    return merged


def validate_metric(name: str, spec: dict[str, Any], where: str = "") -> None:
    """Fail at load time on typos and impossible combinations, not halfway through a run."""
    unknown = set(spec) - AGENT_KEYS
    if unknown:
        raise ConfigError(f"{where}: metric '{name}' has unknown keys {sorted(unknown)}")
    custom = "rubric" in spec or "criteria" in spec
    if not custom and spec.get("type", name) not in library():
        raise ConfigError(f"{where}: '{name}' is not in metric_library.yaml {sorted(library())} "
                          f"and has no rubric: or criteria:")
    if set(spec.get("needs", [])) - set(STANDARD_FIELDS):
        raise ConfigError(f"{where}: metric '{name}' needs must be from {list(STANDARD_FIELDS)}")
    engine = spec.get("engine")
    if engine:
        base = {} if custom else library()[spec.get("type", name)]
        available = {"pegasus"} if base.get("pegasus") else set()
        if custom or base.get("deepeval") or base.get("criteria"):
            available.add("deepeval")
        if engine not in available:
            raise ConfigError(f"{where}: metric '{name}' can't run on '{engine}' (available: {sorted(available)})")


def run_judge(name: str, spec: dict[str, Any], fields: dict[str, Any]) -> Result:
    """Score one metric for one case. Never raises: problems become an ERROR result."""
    metric = definition(name, spec)
    threshold = float(metric.get("threshold", 0.7))
    values = {f: fields.get(metric.get(f, f)) for f in metric["needs"]}
    result = Result(name=name, kind="judge", status=SKIP, threshold=threshold)

    missing = [metric.get(f, f) for f, v in values.items() if _is_empty(v)]
    if missing:
        result.reason = f"skipped: case has no {', '.join(missing)}"
        return result

    try:
        result.engine = pick_engine(metric)
        if result.engine == "pegasus":
            score, reason = _score_pegasus(metric, values, threshold)
        else:
            score, reason = _score_deepeval(name, metric, values, threshold)
    except Exception as exc:  # noqa: BLE001 — surfaced as ERROR, never as a low score
        result.status, result.reason = ERROR, f"{type(exc).__name__}: {exc}"
        return result

    result.score = round(float(score), 4)
    result.status = PASS if result.score >= threshold else FAIL
    result.reason = reason or ""
    return result


def pick_engine(metric: dict[str, Any]) -> str:
    if metric.get("engine"):
        return metric["engine"]
    if metric.get("pegasus") and pegasus_installed():
        return "pegasus"
    if metric.get("deepeval") or metric.get("criteria"):
        if metric.get("pegasus"):
            _warn_once("Pegasus is not installed — Pegasus metrics are running on DeepEval on this machine.")
        return "deepeval"
    raise RuntimeError("this metric only exists in Pegasus, and Pegasus is not installed")


def _score_deepeval(name: str, metric: dict[str, Any], values: dict[str, Any],
                    threshold: float) -> tuple[float, str]:
    import deepeval.metrics as dm
    from deepeval.test_case import LLMTestCase

    from evalkit.cortex import deepeval_llm

    llm = deepeval_llm()
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


def _score_pegasus(metric: dict[str, Any], values: dict[str, Any], threshold: float) -> tuple[float, str]:
    import pandas as pd
    from pegasus.metrics import rag

    from evalkit.cortex import pegasus_llm

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

    judge = getattr(rag, metric["pegasus"])(llm=pegasus_llm(), method=metric.get("method", "pegasus"),
                                            threshold=threshold)
    out = judge.evaluate(frame)
    score = _first(out.get("score"))
    if score is None:
        raise RuntimeError(f"Pegasus returned no score: {out}")
    reason = _first(out.get("reasoning") or out.get("reasons") or out.get("details"))
    return float(score), str(reason or "")


def _geval_param(field_name: str) -> Any:
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


@functools.cache
def pegasus_installed() -> bool:
    return importlib.util.find_spec("pegasus") is not None


@functools.cache
def _warn_once(message: str) -> None:
    print(f"WARNING: {message}")


def _first(value: Any) -> Any:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value


def _is_empty(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return not any(str(v).strip() for v in value)
    return not str(value if value is not None else "").strip()
