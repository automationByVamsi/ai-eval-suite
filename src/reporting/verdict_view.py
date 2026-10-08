"""
The data behind the dashboard's verdict view (no Streamlit here, so it can be tested).

A verdict run (`make verdict`) has, in its run folder:
  results.json            the new build's run (kind: verdict)
  verdict.json            the outcome and every compared row (src/verdict/compare.py save_verdict)
  baseline_results.json   the baseline's full run, as it was at verdict time

From those, this module works out:
  load(run)          the verdict and the baseline run (None when the run isn't a verdict)
  case_changes(...)  per test case: regressed / missing / improved / new / unchanged, and what changed
  metric_changes()   per judge and check: baseline vs current pass rate and mean score
  headline(...)      the one-line reason for PASS / FAIL
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.core.results import Run, load_run
from src.reporting.summary import summarise

# Order the dashboard shows changes in (worst first).
CHANGES = ("regressed", "missing", "improved", "new", "unchanged")


@dataclass
class Verdict:
    run: Run                                  # the new build
    outcome: dict[str, Any]                   # verdict.json
    baseline_run: Run | None                  # the baseline build in full (None for older baselines)

    @property
    def passed(self) -> bool:
        return bool(self.outcome.get("passed"))

    @property
    def baseline_build(self) -> str:
        return str((self.outcome.get("baseline") or {}).get("build") or "?")


def load(run: Run) -> Verdict | None:
    """The verdict saved with this run, or None for an ordinary run."""
    path = run.folder / "verdict.json"
    if run.kind != "verdict" or not path.is_file():
        return None
    outcome = json.loads(path.read_text())
    frozen = run.folder / "baseline_results.json"
    baseline_run = load_run(str(frozen)) if frozen.is_file() and frozen.stat().st_size > 2 else None
    return Verdict(run=run, outcome=outcome, baseline_run=baseline_run)


@dataclass
class CaseChange:
    case_id: str
    change: str                                        # one of CHANGES
    items: list[dict[str, Any]] = field(default_factory=list)   # the rows that changed (not "ok")
    results: list[str] = field(default_factory=list)   # every result compared for this case, e.g. "judge:correctness"


def case_changes(rows: list[dict[str, Any]]) -> dict[str, CaseChange]:
    """
    Group verdict rows ("<case> :: <kind>:<name>") by test case. A case is regressed if any of its results
    regressed, else missing if one didn't run, else improved, else new (only new results), else unchanged.
    """
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_id, _, result = row["result"].partition(" :: ")
        by_case.setdefault(case_id, []).append({**row, "name": result})
    changes = {}
    for case_id, case_rows in by_case.items():
        statuses = {r["status"] for r in case_rows}
        if "regression" in statuses:
            change = "regressed"
        elif "missing" in statuses:
            change = "missing"
        elif "improved" in statuses:
            change = "improved"
        elif statuses == {"new"}:
            change = "new"
        else:
            change = "unchanged"
        order = {"regression": 0, "missing": 1, "improved": 2, "new": 3, "ok": 4}
        items = sorted((r for r in case_rows if r["status"] != "ok" or r["note"]),
                       key=lambda r: order.get(r["status"], 9))
        changes[case_id] = CaseChange(case_id, change, items, [r["name"] for r in case_rows])
    return changes


def describe(item: dict[str, Any]) -> str:
    """'correctness 0.86 -> 0.62' / 'anchor hit pass -> fail' / 'answer non empty: not run this time'."""
    kind, _, name = item["name"].partition(":")
    label = name.replace("_", " ")
    before, after = item.get("baseline") or {}, item.get("current") or {}
    if item["status"] == "missing":
        return f"{label}: not run this time"
    if item["status"] == "new":
        return f"{label}: new ({_rate_text(after)})"
    if kind == "judge" and before.get("mean_score") is not None and after.get("mean_score") is not None:
        return f"{label} {before['mean_score']:.2f} → {after['mean_score']:.2f}"
    return f"{label} {_rate_text(before)} → {_rate_text(after)}"


def _rate_text(summary: dict[str, Any]) -> str:
    rate = summary.get("pass_rate")
    if rate is None:
        return "–"
    if summary.get("n", 1) == 1:
        return "pass" if rate >= 1 else "fail"
    return f"{rate:.0%}"


def metric_changes(baseline_run: Run | None, run: Run) -> list[dict[str, Any]]:
    """Per judge and check: pass rate and mean score in each build (None where it didn't run)."""
    now = {(r["kind"], r["name"]): r for r in summarise([run])}
    before = {(r["kind"], r["name"]): r for r in summarise([baseline_run])} if baseline_run else {}
    rows = []
    for key in list(dict.fromkeys([*before, *now])):
        b, n = before.get(key) or {}, now.get(key) or {}
        if b.get("rate") is None and n.get("rate") is None:
            continue                                   # skipped everywhere in both builds
        rows.append({"kind": key[0], "name": key[1], "group": (n or b).get("group", ""),
                     "baseline_rate": b.get("rate"), "current_rate": n.get("rate"),
                     "baseline_score": b.get("mean_score"), "current_score": n.get("mean_score")})
    return sorted(rows, key=lambda r: r["kind"] != "judge")


def headline(outcome: dict[str, Any], changes: dict[str, CaseChange], errors: int, targets_missed: int) -> str:
    """The reason for the verdict, in one line."""
    parts = []
    regressed = sum(c.change == "regressed" for c in changes.values())
    missing = sum(c.change == "missing" for c in changes.values())
    improved = sum(c.change == "improved" for c in changes.values())
    if regressed:
        parts.append(f"{regressed} test case{'s' * (regressed != 1)} regressed")
    if missing:
        parts.append(f"{missing} with results missing")
    if errors:
        parts.append(f"{errors} could not be evaluated")
    if targets_missed:
        parts.append(f"{targets_missed} release target{'s' * (targets_missed != 1)} missed")
    if not parts:
        parts.append("no regressions against the baseline")
        parts.append("all release targets met" if outcome.get("targets_met", True) else "")
    if improved:
        parts.append(f"{improved} improved")
    return " · ".join(p for p in parts if p)
