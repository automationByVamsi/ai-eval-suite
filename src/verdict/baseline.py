"""
Baselines: save a stable build's per-case pass rates and mean scores to baselines/<agent>/<suite>.json,
plus its full run to <suite>.run.json. Commit both so the team compares against the same baseline.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from src.core import paths
from src.core.results import ERROR, PASS, SKIP, Result, Run, load_run


def baseline_path(agent: str, suite: str) -> Path:
    """Return the path of the baseline summary file."""
    return paths.BASELINES_DIR / agent / f"{suite}.json"


def baseline_run_path(agent: str, suite: str) -> Path:
    """Return the path of the baseline's committed full run."""
    return paths.BASELINES_DIR / agent / f"{suite}.run.json"


def baseline_run_file(agent: str, suite: str) -> Path | None:
    """Return the baseline's full run file: the committed copy, else its original run folder, else None."""
    path = baseline_run_path(agent, suite)
    if path.is_file():
        return path
    summary = baseline_path(agent, suite)
    if summary.is_file():
        run_id = json.loads(summary.read_text()).get("run_id")
        saved = paths.OUTPUTS_DIR / "runs" / str(run_id) / "results.json"
        if run_id and saved.is_file():
            return saved
    return None


def load_baseline_run(agent: str, suite: str) -> Run | None:
    """Load the baseline's full run, or None when only the summary exists."""
    path = baseline_run_file(agent, suite)
    return load_run(str(path)) if path else None


def summarize(run: Run) -> dict[str, dict[str, Any]]:
    """Return pass rate and mean score across reps per "<case_id> :: <kind>:<name>".
    Skipped results are left out."""
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
    """Save a run as the baseline and return the summary path. Refuses runs with errored cases."""
    errors = [c.case_id for c in run.cases if c.status == ERROR]
    if errors:
        raise ValueError(f"Not saving a baseline from a run with errors (cases {errors}). Fix and re-run.")
    run.kind = "baseline"
    saved_run = run.save()
    path = baseline_path(run.agent, run.suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline_run_path(run.agent, run.suite).write_text(saved_run.read_text())
    path.write_text(json.dumps({
        "agent": run.agent,
        "suite": run.suite,
        "build": run.build,
        "reps": run.reps,
        "run_id": run.run_id,
        "judge_temperature": run.judge_temperature,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "results": summarize(run),
    }, indent=2))
    return path
