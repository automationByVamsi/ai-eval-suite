"""
Baseline and verdict: is the new build as good as the last stable one?

  baseline  Take a run of a stable build (ideally --reps 3..5) and store, per case and per
            check/judge, its pass rate and mean score in baselines/<agent>/<suite>.json.
            Commit that file so the whole team compares against the same baseline.

  verdict   Take a run of the new build and compare it with the baseline:
              regression  pass rate dropped by >= PASS_RATE_DROP, or mean score by >= SCORE_DROP
              missing     a check/judge in the baseline didn't run at all this time
              improved / new / ok
            The verdict FAILS on any regression, missing result, or agent/judge error.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from evalkit.config import BASELINES_DIR
from evalkit.results import ERROR, PASS, SKIP, Run

PASS_RATE_DROP = 0.15   # e.g. 100% -> 80% of reps passing is a regression
SCORE_DROP = 0.10       # e.g. faithfulness mean 0.92 -> 0.80 is a regression, even if still above threshold


def baseline_path(agent: str, suite: str) -> Path:
    return BASELINES_DIR / agent / f"{suite}.json"


def summarize(run: Run) -> dict[str, dict[str, Any]]:
    """Per (case, check/judge): pass rate and mean score across reps. Skipped results are left out."""
    grouped: dict[str, list] = defaultdict(list)
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
            "engine": results[0].engine,
        }
    return summary


def save_baseline(run: Run) -> Path:
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


def compare(run: Run) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    """Returns (verdict_passed, rows, baseline)."""
    path = baseline_path(run.agent, run.suite)
    if not path.is_file():
        raise FileNotFoundError(f"No baseline at {path}. Create one with: make baseline")
    baseline = json.loads(path.read_text())
    before, now = baseline["results"], summarize(run)

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
            if b["engine"] != n["engine"]:
                row["note"] = f"engine changed {b['engine']} -> {n['engine']}: scores not comparable"
        rows.append(row)

    errors = any(c.status == ERROR for c in run.cases)
    passed = not errors and not any(r["status"] in ("regression", "missing") for r in rows)
    return passed, rows, baseline


def print_verdict(run: Run, passed: bool, rows: list[dict[str, Any]], baseline: dict[str, Any]) -> None:
    def fmt(s: dict | None) -> str:
        if not s:
            return "-"
        score = f" score {s['mean_score']:.2f}" if s["mean_score"] is not None else ""
        return f"{s['pass_rate']:.0%} pass{score}"

    print(f"\nVERDICT {run.agent}/{run.suite}: build '{run.build or '?'}' vs baseline build "
          f"'{baseline.get('build') or '?'}' ({baseline['reps']} reps -> {run.reps} reps)")
    print("-" * 100)
    for row in rows:
        if row["status"] != "ok" or row["note"]:
            print(f"{row['status'].upper():<11} {row['result']:<55} "
                  f"{fmt(row['baseline']):>18} -> {fmt(row['current']):<18} {row['note']}")
    ok = sum(r["status"] == "ok" for r in rows)
    print(f"{ok} unchanged" if ok else "")
    errors = [c.case_id for c in run.cases if c.status == ERROR]
    if errors:
        print(f"ERRORS in this run (agent/judge could not run): {sorted(set(errors))}")
    print("-" * 100)
    print("VERDICT: PASS - no regressions\n" if passed else "VERDICT: FAIL - see above\n")
