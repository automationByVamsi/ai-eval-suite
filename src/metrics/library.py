"""
The metric library (metric_library.yaml) and the validation of metric settings in agent.yaml.

A library entry says which case fields a metric needs and how each engine implements it:

    faithfulness:
      needs: [question, answer, contexts]
      pegasus: Faithfulness              # class in pegasus.metrics.rag
      deepeval: FaithfulnessMetric       # class in deepeval.metrics

An agent then uses it by name in its agent.yaml, with a threshold:

    metrics:
      faithfulness: {threshold: 0.8}
      tone: {rubric: rubrics/tone.md}    # custom judge: not in the library, runs on DeepEval GEval

Judges read four standard fields. A metric can read one of them from another parser field,
e.g. `answer: rewritten_query` judges the rewritten query instead of the final answer.

Pegasus metrics outside pegasus.metrics.rag (e.g. agentic ResponseAlignment) say where they live
and what Pegasus calls each input:

    response_alignment:
      needs: [question, answer]
      pegasus: ResponseAlignment
      module: agentic                                   # pegasus.metrics.agentic (default: rag)
      columns: {question: query, answer: agent_response, background: background}

Pegasus safety metrics (e.g. Hallucination) take separate arguments instead of a one-row DataFrame:

    hallucination:
      pegasus: Hallucination
      module: safety
      columns: {question: query, answer: text, contexts: context}
      call: keywords                                    # evaluate(query=..., text=..., context=[...])

An agent's metric can also set `background:` (fixed text for Pegasus' background column) and
`options:` (extra arguments for the Pegasus class, e.g. {use_ground_truth: true, json_path: ...}).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from src.core import paths
from src.core.exceptions import ConfigError

STANDARD_FIELDS = ("question", "answer", "contexts", "expected_answer")

# Keys allowed in metric_library.yaml entries, and in an agent's `metrics:` entries.
LIBRARY_KEYS = {"needs", "pegasus", "deepeval", "criteria", "module", "columns", "call", *STANDARD_FIELDS}
AGENT_KEYS = {"type", "threshold", "rubric", "criteria", "needs", "engine", "method", "background", "options",
              *STANDARD_FIELDS}
COLUMN_SOURCES = {*STANDARD_FIELDS, "background"}     # what a `columns:` entry can map from


SETTINGS = ("judge_temperature",)                      # top-level settings in metric_library.yaml, not metrics


@functools.cache
def _file() -> dict[str, Any]:
    return yaml.safe_load(paths.METRIC_LIBRARY.read_text()) or {}


@functools.cache
def judge_temperature() -> float:
    """`judge_temperature:` in metric_library.yaml (default 0.0): the temperature every judge LLM runs at."""
    value = _file().get("judge_temperature", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ConfigError(f"{paths.METRIC_LIBRARY.name}: judge_temperature must be a number from 0 to 1 "
                          f"(got {value!r})")
    return float(value)


@functools.cache
def library() -> dict[str, dict[str, Any]]:
    """metric_library.yaml's metrics, checked once per process."""
    entries = {name: entry for name, entry in _file().items() if name not in SETTINGS}
    for name, entry in entries.items():
        where = f"{paths.METRIC_LIBRARY.name}: '{name}'"
        if set(entry) - LIBRARY_KEYS:
            raise ConfigError(f"{where} has unknown keys {sorted(set(entry) - LIBRARY_KEYS)}")
        if not entry.get("needs") or set(entry["needs"]) - set(STANDARD_FIELDS):
            raise ConfigError(f"{where} needs `needs:` from {list(STANDARD_FIELDS)}")
        if not (entry.get("pegasus") or entry.get("deepeval") or entry.get("criteria")):
            raise ConfigError(f"{where} needs at least one of pegasus / deepeval / criteria")
        if set(entry.get("columns") or {}) - COLUMN_SOURCES:
            raise ConfigError(f"{where} columns: keys must be from {sorted(COLUMN_SOURCES)}")
        if entry.get("call", "keywords") != "keywords":
            raise ConfigError(f"{where} call: can only be `keywords` (leave it out for a one-row DataFrame)")
    return entries


def is_custom(spec: dict[str, Any]) -> bool:
    """A metric the agent defines itself (a rubric file or inline criteria), not a library metric."""
    return "rubric" in spec or "criteria" in spec


def definition(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """
    Everything needed to score one metric: the library entry (for library metrics) overlaid with
    the agent's settings. A rubric file's text becomes `criteria`.
    """
    base = {"needs": ["question", "answer"]} if is_custom(spec) else library()[spec.get("type", name)]
    merged = {**base, **spec}
    if "rubric" in merged:
        merged["criteria"] = Path(merged["rubric"]).read_text().strip()
    return merged


def validate_metric(name: str, spec: dict[str, Any], where: str = "") -> None:
    """Fail at load time on typos and impossible combinations — not halfway through a run."""
    unknown = set(spec) - AGENT_KEYS
    if unknown:
        raise ConfigError(f"{where}: metric '{name}' has unknown keys {sorted(unknown)}")
    custom = is_custom(spec)
    if not custom and spec.get("type", name) not in library():
        raise ConfigError(f"{where}: '{name}' is not in metric_library.yaml {sorted(library())} "
                          f"and has no rubric: or criteria:")
    if set(spec.get("needs", [])) - set(STANDARD_FIELDS):
        raise ConfigError(f"{where}: metric '{name}' needs must be from {list(STANDARD_FIELDS)}")
    if "options" in spec and not isinstance(spec["options"], dict):
        raise ConfigError(f"{where}: metric '{name}' options: must be a mapping, e.g. {{use_ground_truth: true}}")
    engine = spec.get("engine")
    if engine:
        # `engine:` forces one engine; it must be one the metric actually has.
        base = {} if custom else library()[spec.get("type", name)]
        available = {"pegasus"} if base.get("pegasus") else set()
        if custom or base.get("deepeval") or base.get("criteria"):
            available.add("deepeval")
        if engine not in available:
            raise ConfigError(f"{where}: metric '{name}' can't run on '{engine}' (available: {sorted(available)})")
