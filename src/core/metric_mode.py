"""
Resolve which scoring backend runs for each suite judge.

Suite YAML owns the preferred mode (default: pegasus). Catalog metrics declare
which backends they support. Custom GEval / DeepEval-only metrics stay on
deepeval even when the suite prefers pegasus.

Priority for the preferred mode:
  1. per-judge ``mode:`` override in the suite
  2. ``METRIC_MODE`` env (optional escape hatch for Make / CI)
  3. suite-level ``mode:``
  4. DEFAULT_SUITE_MODE (pegasus)
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_SUITE_MODE = "pegasus"

PEGASUS_MODES = frozenset({"pegasus", "pegasus_ragas", "pegasus_deepeval"})
DEEPEVAL_MODE = "deepeval"

# Built-in types that can run through lbg-pegasus (and usually DeepEval too).
_PEGASUS_CAPABLE_TYPES = frozenset(
    {
        "relevance",
        "answer_relevancy",
        "faithfulness",
        "correctness",
        "answer_correctness",
        "context_precision",
        "context_recall",
    }
)

# Types with no Pegasus path in this repo — always DeepEval / GEval.
_DEEPEVAL_ONLY_TYPES = frozenset(
    {
        "geval",
        "keyword_match",
        "summarization",
        "task_completion",
        "contextual_relevancy",
        "hallucination",
        "tool_correctness",
    }
)

# Pegasus-only in this repo (no DeepEval wrapper registered).
_PEGASUS_ONLY_TYPES = frozenset({"context_precision", "context_recall"})


def is_pegasus_mode(mode: str | None) -> bool:
    """Return True when mode selects the lbg-pegasus path."""
    return str(mode or "").strip().lower() in PEGASUS_MODES


def normalize_mode(mode: str | None) -> str:
    """Normalize a mode string; empty → DEFAULT_SUITE_MODE."""
    m = str(mode or "").strip().lower()
    return m or DEFAULT_SUITE_MODE


def backends_for(cfg: dict[str, Any]) -> list[str]:
    """
    Return supported backends for a catalog metric, most-preferred first.

    Explicit ``backends:`` in YAML wins. Otherwise inferred from ``type``.
    """
    raw = cfg.get("backends")
    if isinstance(raw, list) and raw:
        out: list[str] = []
        for item in raw:
            b = str(item).strip().lower()
            if b == "pegasus" or b in PEGASUS_MODES:
                if "pegasus" not in out:
                    out.append("pegasus")
            elif b == DEEPEVAL_MODE:
                if DEEPEVAL_MODE not in out:
                    out.append(DEEPEVAL_MODE)
            else:
                if b and b not in out:
                    out.append(b)
        return out or [DEEPEVAL_MODE]

    mtype = str(cfg.get("type") or cfg.get("name") or "").strip().lower()

    if mtype in _DEEPEVAL_ONLY_TYPES or mtype == "geval":
        return [DEEPEVAL_MODE]

    if mtype in _PEGASUS_ONLY_TYPES:
        return ["pegasus"]

    if mtype in _PEGASUS_CAPABLE_TYPES:
        return ["pegasus", DEEPEVAL_MODE]

    # Legacy: catalog already pinned a mode.
    pinned = str(cfg.get("mode") or "").strip().lower()
    if is_pegasus_mode(pinned):
        return ["pegasus", DEEPEVAL_MODE]
    if pinned == DEEPEVAL_MODE:
        return [DEEPEVAL_MODE]

    return [DEEPEVAL_MODE]


def preferred_suite_mode(
    suite_mode: str | None,
    *,
    env: dict[str, str] | None = None,
) -> str:
    """Suite mode, optionally overridden by METRIC_MODE env."""
    environ = env if env is not None else os.environ
    env_mode = str(environ.get("METRIC_MODE") or "").strip().lower()
    if env_mode:
        return normalize_mode(env_mode)
    return normalize_mode(suite_mode)


def resolve_metric_mode(
    preferred: str,
    cfg: dict[str, Any],
    *,
    judge_override: str | None = None,
) -> str:
    """
    Pick the effective mode for one metric.

    If the preferred / overridden mode is unsupported, fall back to the first
    backend the metric declares (GEval customs → deepeval).
    """
    backends = backends_for(cfg)
    candidate = normalize_mode(judge_override or preferred)

    if is_pegasus_mode(candidate):
        if "pegasus" in backends:
            return candidate
        # Custom / DeepEval-only: ignore suite preference.
        if DEEPEVAL_MODE in backends:
            return DEEPEVAL_MODE
        return backends[0]

    if candidate == DEEPEVAL_MODE:
        if DEEPEVAL_MODE in backends:
            return DEEPEVAL_MODE
        if "pegasus" in backends:
            return "pegasus"
        return backends[0]

    # Unknown mode string — prefer an exact backend match, else first backend.
    if candidate in backends:
        return candidate
    if "pegasus" in backends and is_pegasus_mode(candidate):
        return candidate
    if DEEPEVAL_MODE in backends:
        return DEEPEVAL_MODE
    if "pegasus" in backends:
        return "pegasus"
    return backends[0]


def apply_resolved_mode(cfg: dict[str, Any], mode: str) -> dict[str, Any]:
    """Return a copy of cfg with ``mode`` set to the resolved backend."""
    out = dict(cfg)
    out["mode"] = mode
    return out
