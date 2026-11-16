"""Pass rate, mean score and unstable cases for every check and judge across one or more runs.

Rate is passes / (passes + fails); skips and errors are counted separately and never move it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.core.results import ERROR, FAIL, PASS, SKIP, Run


def summarise(runs: list[Run]) -> list[dict[str, Any]]:
    """Return one row per check / judge across every case and rep of the runs, judges first."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    per_case: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for run in runs:
        for case in run.cases:
            for result in case.results:
                key = (result.kind, result.name)
                row = rows.setdefault(key, {"name": result.name, "kind": result.kind, "group": result.group,
                                            PASS: 0, FAIL: 0,
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
    # Stable sort: judges first, otherwise first-seen order.
    return sorted(summary, key=lambda r: r["kind"] != "judge")


def time_split(runs: list[Run]) -> dict[str, float]:
    """Return the mean of each numeric `*_seconds` field across all cases, keyed without the suffix ({} if none)."""
    values: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for case in run.cases:
            for name, value in (case.details or {}).items():
                if name.endswith("_seconds") and isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[name.removesuffix("_seconds")].append(value)
    return {name: round(sum(v) / len(v), 2) for name, v in values.items()}


def print_summary(rows: list[dict[str, Any]], title: str) -> None:
    """Print the rates table; rows skipped in every case are listed on one line at the end."""
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
