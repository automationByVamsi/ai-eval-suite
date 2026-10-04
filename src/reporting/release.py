"""
Release view of a run: the suite's targets (agent.yaml `targets:`) and, with REPS > 1, whether each
case gave the same evidence and passed every time (`consistency:`).

Targets are pass RATES across the run, not per-case thresholds:
    targets:
      correctness: 0.90      at least 90% of cases pass the correctness judge (each at its own 0.7)
      within_60s: 0.95       a check: at least 95% of cases pass it
      error_rate: 0.05       at most 5% of cases could not be evaluated (agent down, lookup failed ...)
      case_pass_rate: 0.90   at least 90% of cases pass everything
      consistency: 1.0       with REPS > 1: every case consistent (see below)
A target whose judge / check never gave a verdict in this run is "no data" and NOT met.

Consistency (REPS > 1), per case, from agent.yaml:
    consistency:
      same: evidence_page_ids    this field must match across every repetition (the source articles)
      min_overlap: 1.0           1.0 = identical; the lowest overlap between any two repetitions counts
      all_pass: [correctness]    these must pass in every repetition (default: every judge)
A case is consistent only if both hold. An inconsistent case counts as a failure (HIVE-6165).

Used by: the console report, the dashboard and the verdict (`make verdict` fails on a missed target).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from src.core.results import ERROR, FAIL, PASS, CaseResult, Run
from src.reporting.summary import summarise

MAX_TARGETS = {"error_rate"}            # targets that are a ceiling, not a floor


def consistency(run: Run) -> list[dict[str, Any]]:
    """One row per case that ran more than once: evidence overlap, passes per result, consistent or not."""
    spec = run.consistency or {}
    reps_by_case: dict[str, list[CaseResult]] = defaultdict(list)
    for case in run.cases:
        reps_by_case[case.case_id].append(case)
    rows = []
    for case_id, reps in reps_by_case.items():
        if len(reps) < 2:
            continue
        overlap = None
        if spec.get("same"):
            sets = [frozenset(str(x) for x in _as_list((c.details or {}).get(spec["same"]))) for c in reps]
            overlap = min(_jaccard(a, b) for a, b in combinations(sets, 2))
        wanted = spec.get("all_pass") or sorted({r.name for c in reps for r in c.results if r.kind == "judge"})
        passes = {}
        for name in wanted:
            outcomes = [r.status for c in reps for r in c.results if r.name == name and r.status in (PASS, FAIL)]
            if outcomes:
                passes[name] = (outcomes.count(PASS), len(outcomes))
        errors = sum(c.status == ERROR for c in reps)
        evidence_ok = overlap is None or overlap >= float(spec.get("min_overlap", 1.0))
        answers_ok = all(p == n for p, n in passes.values())
        reasons = []
        if not evidence_ok:
            reasons.append(f"{spec['same']} differed between repetitions (overlap {overlap:.2f})")
        reasons += [f"{name} passed {p}/{n}" for name, (p, n) in passes.items() if p != n]
        if errors:
            reasons.append(f"{errors} repetition(s) could not be evaluated")
        rows.append({"case": case_id, "reps": len(reps), "evidence_overlap": overlap,
                     "passes": {k: f"{p}/{n}" for k, (p, n) in passes.items()},
                     "consistent": evidence_ok and answers_ok and not errors, "why": "; ".join(reasons)})
    return rows


def targets(run: Run) -> list[dict[str, Any]]:
    """One row per target: actual value, target, met (False when there is no data)."""
    if not run.targets:
        return []
    rates = {row["name"]: row for row in summarise([run])}
    cases = run.cases
    rows = []
    for name, target in run.targets.items():
        actual, detail = None, ""
        if name == "error_rate" and cases:
            errors = sum(c.status == ERROR for c in cases)
            actual, detail = errors / len(cases), f"{errors}/{len(cases)} case runs"
        elif name == "case_pass_rate" and cases:
            passed = sum(c.status == PASS for c in cases)
            actual, detail = passed / len(cases), f"{passed}/{len(cases)} case runs"
        elif name == "consistency":
            rows_c = consistency(run)
            if rows_c:
                ok = sum(r["consistent"] for r in rows_c)
                actual, detail = ok / len(rows_c), f"{ok}/{len(rows_c)} cases consistent"
            else:
                detail = "needs REPS > 1"
        elif name in rates and rates[name]["rate"] is not None:
            row = rates[name]
            actual, detail = row["rate"], f"{row[PASS]}/{row[PASS] + row[FAIL]} passed"
        else:
            detail = "no verdict in this run (skipped everywhere, or not run)"
        if actual is None:
            met = None if name == "consistency" and run.reps < 2 else False
        else:
            met = actual <= target if name in MAX_TARGETS else actual >= target
        rows.append({"name": name, "actual": actual, "target": target, "met": met,
                     "ceiling": name in MAX_TARGETS, "detail": detail})
    return rows


def gate(run: Run) -> tuple[bool, list[dict[str, Any]]]:
    """(every target met, the target rows). Targets that don't apply (consistency at REPS=1) are ignored."""
    rows = targets(run)
    return all(r["met"] is not False for r in rows), rows


def _jaccard(a: frozenset, b: frozenset) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]
