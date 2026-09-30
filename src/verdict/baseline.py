"""
Baselines: what "good" looked like for the last stable build.

`make baseline AGENT=.. SUITE=.. BUILD=1.4.0 REPS=5` runs the stable build (ideally 3-5 reps,
because LLM agents and judges vary run to run) and stores, per case and per check/judge, the
pass rate and mean score in baselines/<agent>/<suite>.json.

Commit that file so the whole team compares against the same baseline.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from src.core import paths
from src.core.results import ERROR, PASS, SKIP, Result, Run


def baseline_path(agent: str, suite: str) -> Path:
    return paths.BASELINES_DIR / agent / f"{suite}.json"


def summarize(run: Run) -> dict[str, dict[str, Any]]:
    """
    Per "<case_id> :: <kind>:<name>": pass rate and mean score across reps.

    Skipped results are left out — a judge that had no data to judge says nothing about the build.
    """
    grouped: dict[str, list[Result]] = defaultdict(list)
    for case in run.cases:
        for r in case.results:
            if r.status != SKIP:
                grouped[f"{case.case_id} :: {r.kind}:{r.name}"].append(r)
    summary = {}
    for key, results in sorted(grouped.items()):
        scores = [r.score for r in results if r.score is not None]
        summary[key] = {
            "pass_rate": round(sum(r.status == PASS for r in results) / len(results), 3),
            "mean_score": round(mean(scores), 3) if scores else None,
            "n": len(results),
            "engine": results[0].engine,   # Pegasus and DeepEval scores aren't comparable; compare warns
        }
    return summary


def save_baseline(run: Run) -> Path:
    """Save a run as the baseline. Refused if any case errored: a broken run is not a baseline."""
    errors = [c.case_id for c in run.cases if c.status == ERROR]
    if errors:
        raise ValueError(f"Not saving a baseline from a run with errors (cases {errors}). Fix and re-run.")
    path = baseline_path(run.agent, run.suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "agent": run.agent,
        "suite": run.suite,
        "build": run.build,
        "reps": run.reps,
        "run_id": run.run_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "results": summarize(run),
    }, indent=2))
    return path
