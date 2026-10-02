"""
Rates across a whole run (or several runs): how often each check and judge passed.

    anchor_hit   check   18/24 = 75%   (6 fail, 4 skip)
    faithfulness judge   20/22 = 91%   mean 0.86   (2 error)

  rate     passes / (passes + fails). Skips (the case has no expected value for it) and errors (it
           could not run) are left out of the rate and counted separately, so they never pull the
           rate up or down.
  mean     the average score, for judges and scored checks (precision, recall).
  per case with repetitions (REPS=n, or several runs together), e.g. anchor_hit KA_GLD_CVH_044
           hit 3/5 — shown for cases whose outcome changed between repetitions (the unstable ones).

Used by: the console report after every run (print_run), results.json ("summary"), and
`make summary` (several saved runs together).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.core.results import ERROR, FAIL, PASS, SKIP, Run


def summarise(runs: list[Run]) -> list[dict[str, Any]]:
    """One row per check / judge name, across every case and repetition of the given runs."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    per_case: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for run in runs:
        for case in run.cases:
            for result in case.results:
                key = (result.kind, result.name)
                row = rows.setdefault(key, {"name": result.name, "kind": result.kind, PASS: 0, FAIL: 0,
                                            SKIP: 0, ERROR: 0, "scores": []})
                row[result.status] += 1
                if result.score is not None:
                    row["scores"].append(result.score)
                if result.status in (PASS, FAIL):
                    per_case[key][case.case_id].append(result.status)

    summary = []
    for key, row in rows.items():
        judged = row[PASS] + row[FAIL]
        scores = row.pop("scores")
        unstable = {case_id: f"{outcomes.count(PASS)}/{len(outcomes)}"
                    for case_id, outcomes in sorted(per_case[key].items()) if len(set(outcomes)) > 1}
        summary.append({**row, "rate": round(row[PASS] / judged, 4) if judged else None,
                        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
                        "cases": len(per_case[key]), "unstable": unstable})
    # Judges first, then checks; within each, the order they first appeared.
    return sorted(summary, key=lambda r: r["kind"] != "judge")


def print_summary(rows: list[dict[str, Any]], title: str) -> None:
    """The rates table (rows that never ran — all skipped — are listed on one line at the end)."""
    print(f"\n{title}")
    print("-" * 72)
    never = []
    for row in rows:
        if row["rate"] is None and not row[ERROR]:
            never.append(row["name"])
            continue
        judged = row[PASS] + row[FAIL]
        rate = f"{row[PASS]}/{judged} = {row['rate']:.0%}" if row["rate"] is not None else "-"
        mean = f"  mean {row['mean_score']:.2f}" if row["mean_score"] is not None else ""
        extra = ", ".join(f"{row[s]} {s}" for s in (SKIP, ERROR) if row[s])
        line = f"  {row['name']:<28} {row['kind']:<6} {rate:<16}{mean}" + (f"  ({extra})" if extra else "")
        print(line.rstrip())
        for case_id, hits in row["unstable"].items():
            print(f"      unstable: {case_id} passed {hits}")
    if never:
        print(f"  skipped in every case (no expected data, or its when: never held): {', '.join(never)}")
