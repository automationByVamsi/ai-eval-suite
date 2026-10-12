"""Release checks for a run: agent.yaml `targets:` (pass rates across the run) and, with REPS > 1, `consistency:`.

A target with no data is not met. A case is consistent when its `same` field and `all_pass` judges hold in every rep.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from src.core.results import ERROR, FAIL, PASS, CaseResult, Run
from src.reporting.summary import summarise

MAX_TARGETS = {"error_rate"}            # targets that are a ceiling, not a floor


def consistency(run: Run) -> list[dict[str, Any]]:
    """Return one consistency row per case that ran more than once, inconsistent first.
    Each row has overlap, also, passes, not_judged, consistent and why."""
    spec = run.consistency or {}

    reps_by_case: dict[str, list[CaseResult]] = defaultdict(list)
    for case in run.cases:
        reps_by_case[case.case_id].append(case)

    rows = [_consistency_row(case_id, reps, spec) for case_id, reps in reps_by_case.items() if len(reps) >= 2]
    rows.sort(key=lambda r: r["consistent"])        # False (inconsistent) sorts before True
    return rows


def _consistency_row(case_id: str, reps: list[CaseResult], spec: dict) -> dict[str, Any]:
    """Return the consistency row for one case from all of its reps."""
    same = spec.get("same")
    overlap = _overlap(reps, same) if same else None
    also = {field: _overlap(reps, field) for field in spec.get("report") or []}   # shown only, not gated
    evidence_ok = overlap is None or overlap >= float(spec.get("min_overlap", 1.0))

    passes, not_judged = _judge_outcomes(reps, spec)
    answers_ok = all(p == n for p, n in passes.values())

    errors = sum(c.status == ERROR for c in reps)

    reasons = []
    if not evidence_ok:
        reasons.append(f"{field_label(same)} changed between runs ({overlap:.0%} in common)")
    reasons += [f"{name} passed {p} of {n} runs" for name, (p, n) in passes.items() if p != n]
    if errors:
        reasons.append(f"{errors} run(s) could not be evaluated")

    return {"case": case_id, "reps": len(reps), "same": same, "overlap": overlap, "also": also,
            "passes": {k: f"{p}/{n}" for k, (p, n) in passes.items()}, "not_judged": not_judged,
            "consistent": evidence_ok and answers_ok and not errors, "why": "; ".join(reasons)}


def _judge_outcomes(reps: list[CaseResult], spec: dict) -> tuple[dict, dict]:
    """Return (passes, not_judged): e.g. {"correctness": (4, 5)}, and {judge: reason} for judges
    skipped in every rep."""
    wanted = spec.get("all_pass") or sorted({r.name for c in reps for r in c.results if r.kind == "judge"})
    passes, not_judged = {}, {}
    for name in wanted:
        results = [r for c in reps for r in c.results if r.name == name]
        outcomes = [r.status for r in results if r.status in (PASS, FAIL)]
        if outcomes:
            passes[name] = (outcomes.count(PASS), len(outcomes))
        elif results:
            reason = next((r.reason for r in results if r.reason), "")
            not_judged[name] = reason.removeprefix("skipped: ") or "skipped in every run"
    return passes, not_judged


def field_label(field: str | None) -> str:
    """Turn a field name into readable words: anchor_page_ids -> 'anchor pages'."""
    words = (field or "").removesuffix("_ids").removesuffix("_id").replace("_", " ").strip()
    return words + ("s" if words and not words.endswith("s") else "")


def _overlap(reps: list[CaseResult], field: str) -> float:
    """Return the lowest Jaccard overlap of a field's values between any two reps."""
    sets = [frozenset(str(x) for x in _as_list((c.details or {}).get(field))) for c in reps]
    return min(_jaccard(a, b) for a, b in combinations(sets, 2))


def targets(run: Run) -> list[dict[str, Any]]:
    """Return one row per target: actual value, target and met (False when there is no data)."""
    if not run.targets:
        return []
    rates = {row["name"]: row for row in summarise([run])}      # pass rate of each judge / check
    rows = []
    for name, target in run.targets.items():
        actual, detail = _target_value(run, name, rates)
        if actual is None:
            # No data is "not met", except consistency at REPS=1, which doesn't apply (None; gate() ignores it).
            met = None if name == "consistency" and run.reps < 2 else False
        elif name in MAX_TARGETS:
            met = actual <= target
        else:
            met = actual >= target
        rows.append({"name": name, "actual": actual, "target": target, "met": met,
                     "ceiling": name in MAX_TARGETS, "detail": detail})
    return rows


def _target_value(run: Run, name: str, rates: dict[str, dict]) -> tuple[float | None, str]:
    """Return (value, short detail) for one target; value is None when there is nothing to measure."""
    cases = run.cases
    if name == "error_rate" and cases:
        errors = sum(c.status == ERROR for c in cases)
        return errors / len(cases), f"{errors}/{len(cases)} case runs"
    if name == "case_pass_rate" and cases:
        passed = sum(c.status == PASS for c in cases)
        return passed / len(cases), f"{passed}/{len(cases)} case runs"
    if name == "consistency":
        rows = consistency(run)
        if not rows:
            return None, "needs more than one run per case (REPS > 1)"
        ok = sum(r["consistent"] for r in rows)
        return ok / len(rows), f"{ok}/{len(rows)} cases consistent"
    if name in rates and rates[name]["rate"] is not None:       # a judge or a check
        row = rates[name]
        return row["rate"], f"{row[PASS]}/{row[PASS] + row[FAIL]} passed"
    return None, "no result in this run (skipped in every case, or not run)"


def gate(run: Run) -> tuple[bool, list[dict[str, Any]]]:
    """Return (every target met, target rows), ignoring targets that don't apply (consistency at REPS=1)."""
    rows = targets(run)
    return all(r["met"] is not False for r in rows), rows


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Return the Jaccard similarity of two sets (1.0 when both are empty)."""
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _as_list(value: Any) -> list[Any]:
    """Return value as a list: None / "" -> [], a single value -> [value]."""
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]
