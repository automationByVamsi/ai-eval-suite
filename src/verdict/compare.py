"""
The verdict: compare a new build's run with the baseline; each row is regression / missing / improved / new / ok.
Fails on any regression, missing result or errored case. Tolerances are PASS_RATE_DROP and SCORE_DROP.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.results import ERROR, Run
from src.verdict.baseline import baseline_path, baseline_run_file, summarize

PASS_RATE_DROP = 0.15   # e.g. 100% -> 80% of reps passing is a regression
SCORE_DROP = 0.10       # e.g. faithfulness mean 0.92 -> 0.80 is a regression, even if still above threshold


def compare(run: Run) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    """Return (verdict passed, one row per case check/judge, the baseline file's content)."""
    path = baseline_path(run.agent, run.suite)
    if not path.is_file():
        raise FileNotFoundError(f"No baseline at {path}. Create one with: make baseline")
    baseline = json.loads(path.read_text())
    before, now = baseline["results"], summarize(run)

    # Scores at different judge temperatures or from different engines are not comparable.
    temperature_note = ""
    if "judge_temperature" in baseline and baseline["judge_temperature"] != run.judge_temperature:
        temperature_note = (f"judge temperature changed {baseline['judge_temperature']} -> "
                            f"{run.judge_temperature}: scores not comparable")

    rows = []
    for key in sorted(set(before) | set(now)):
        b, n = before.get(key), now.get(key)
        row = {"result": key, "baseline": b, "current": n, "status": "ok", "note": ""}
        if n is None:
            row["status"] = "missing"
        elif b is None:
            row["status"] = "new"
        else:
            rate_delta = n["pass_rate"] - b["pass_rate"]
            score_delta = (n["mean_score"] - b["mean_score"]
                           if n["mean_score"] is not None and b["mean_score"] is not None else 0.0)
            if rate_delta <= -PASS_RATE_DROP or score_delta <= -SCORE_DROP:
                row["status"] = "regression"
            elif rate_delta >= PASS_RATE_DROP or score_delta >= SCORE_DROP:
                row["status"] = "improved"
            notes = []
            if b["engine"] != n["engine"]:
                notes.append(f"engine changed {b['engine']} -> {n['engine']}: scores not comparable")
            if temperature_note and ":: judge:" in key:
                notes.append(temperature_note)
            row["note"] = "; ".join(notes)
        rows.append(row)

    errors = any(c.status == ERROR for c in run.cases)
    passed = not errors and not any(r["status"] in ("regression", "missing") for r in rows)
    return passed, rows, baseline


def save_verdict(run: Run, passed: bool, rows: list[dict[str, Any]], baseline: dict[str, Any],
                 targets_met: bool) -> Path:
    """Save verdict.json and a copy of the baseline's full run in the run folder; return the verdict path."""
    run.kind = "verdict"
    run.save()
    source = baseline_run_file(run.agent, run.suite)
    if source is not None:
        (run.folder / "baseline_results.json").write_text(source.read_text())
    path = run.folder / "verdict.json"
    path.write_text(json.dumps({
        "passed": passed and targets_met,           # the overall verdict, as `make verdict` exits
        "no_regressions": passed,
        "targets_met": targets_met,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
        "tolerances": {"pass_rate_drop": PASS_RATE_DROP, "score_drop": SCORE_DROP},
        "baseline": {k: baseline.get(k) for k in ("build", "run_id", "reps", "saved_at", "judge_temperature")},
        "has_baseline_run": source is not None,
        "rows": rows,
    }, indent=2, default=str))
    return path
