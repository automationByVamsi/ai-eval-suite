"""
Console reports: one line per case, the reason for everything that failed, then the rate of every
check and judge across the run (src/reporting/summary.py).

Used by: the CLI after make run / baseline / verdict.
"""

from __future__ import annotations

from typing import Any

from src.core.results import ERROR, FAIL, PASS, SKIP, Run
from src.reporting.release import consistency, gate
from src.reporting.summary import print_summary, summarise

RULE = "-" * 72


def print_run(run: Run) -> None:
    """Per case: PASS / FAIL / ERROR, then every judge (score + engine) and any failing check. Then totals."""
    icon = {PASS: "PASS ", FAIL: "FAIL ", ERROR: "ERROR"}
    temperature = f"  judge temperature={run.judge_temperature}" if run.judge_temperature is not None else ""
    print(f"\n{run.agent} / {run.suite}" + (f"  build={run.build}" if run.build else "") + temperature)
    print(RULE)
    for case in run.cases:
        rep = f" (rep {case.rep + 1})" if run.reps > 1 else ""
        skipped = sum(r.status == SKIP for r in case.results)
        note = f"  [{skipped} skipped]" if skipped else ""
        print(f"{icon[case.status]} {case.case_id}{rep}{note}")
        if case.error:
            print(f"        {case.error}")
        for r in case.results:
            # Judges: always shown, with score and engine (so you can see Pegasus vs DeepEval).
            # Checks: only when they fail — passing checks would just be noise.
            if r.kind == "judge" and r.status != SKIP:
                score = f" score={r.score:.2f}/{r.threshold}" if r.score is not None else ""
                reason = f" {r.reason}" if r.status in (FAIL, ERROR) else ""
                print(f"        {r.status.upper():<5} judge:{r.name}{score} [{r.engine or '-'}]{reason}".rstrip())
            elif r.status in (FAIL, ERROR):
                print(f"        {r.status.upper():<5} {r.kind}:{r.name} {r.reason}".rstrip())
    reps = f" x {run.reps} reps" if run.reps > 1 else ""
    print_summary(summarise([run]), f"Rates over {len({c.case_id for c in run.cases})} case(s){reps}")
    print_release(run)
    counts = {s: sum(c.status == s for c in run.cases) for s in (PASS, FAIL, ERROR)}
    print(RULE)
    print(f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[ERROR]} errors"
          f"  ->  {run.folder / 'results.json'}\n")


def print_release(run: Run) -> None:
    """The suite's targets (met / missed) and, with REPS > 1, the cases that were not consistent."""
    passed, rows = gate(run)
    if rows:
        print(f"\nTargets ({'all met' if passed else 'NOT all met'})")
        print(RULE)
        for r in rows:
            mark = {True: "MET   ", False: "MISSED", None: "n/a   "}[r["met"]]
            actual = "-" if r["actual"] is None else f"{r['actual']:.0%}"
            sign = "<=" if r["ceiling"] else ">="
            print(f"  {mark} {r['name']:<28} {actual:>5}  (target {sign} {r['target']:.0%})  {r['detail']}")
    if run.reps > 1:
        rows_c = consistency(run)
        bad = [r for r in rows_c if not r["consistent"]]
        print(f"\nConsistency over {run.reps} runs: {len(rows_c) - len(bad)}/{len(rows_c)} cases consistent")
        for r in bad:
            print(f"  INCONSISTENT {r['case']}: {r['why']}")
        for r in rows_c:
            for name, why in r["not_judged"].items():
                print(f"  note: {r['case']} {name} not judged in any run ({why})")
        if rows_c:
            print("  The pages and answer of every run: make dashboard -> Consistency tab")


def print_verdict(run: Run, passed: bool, rows: list[dict[str, Any]], baseline: dict[str, Any]) -> None:
    """Only the rows that changed (regressions, missing, improved, new, notes), then PASS / FAIL."""
    def fmt(summary: dict | None) -> str:
        if not summary:
            return "-"
        score = f" score {summary['mean_score']:.2f}" if summary["mean_score"] is not None else ""
        return f"{summary['pass_rate']:.0%} pass{score}"

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
