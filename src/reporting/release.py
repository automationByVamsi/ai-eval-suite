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
      same: anchor_page_ids      this field must match across every repetition (the main source pages)
      min_overlap: 1.0           1.0 = identical; the lowest overlap between any two repetitions counts
      all_pass: [correctness]    these must pass in every repetition (default: every judge)
      report: [cited_page_ids]   overlap shown for these too, but they don't decide consistency
A case is consistent only if `same` and `all_pass` both hold. An inconsistent case counts as a failure.
The answer's wording may differ between repetitions; its meaning is checked by `all_pass`.

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
    """
    One row per case that ran more than once, inconsistent cases first:
      overlap      lowest overlap of `same` between any two repetitions (None without `same`)
      also         {field: overlap} for the `report` fields (shown, not gated)
      passes       {result: "k/n"} for `all_pass` results that gave a verdict
      not_judged   {result: why} for `all_pass` results skipped in every repetition
      consistent   True / False;  why: the reasons in plain words
    """
    spec = run.consistency or {}

    # Gather the runs of each case together: case id -> [run 1, run 2, ...]
    reps_by_case: dict[str, list[CaseResult]] = defaultdict(list)
    for case in run.cases:
        reps_by_case[case.case_id].append(case)

    # Only cases that ran more than once can be compared with themselves.
    rows = [_consistency_row(case_id, reps, spec) for case_id, reps in reps_by_case.items() if len(reps) >= 2]
    rows.sort(key=lambda r: r["consistent"])        # False (inconsistent) sorts before True
    return rows


def _consistency_row(case_id: str, reps: list[CaseResult], spec: dict) -> dict[str, Any]:
    """The consistency result of one case, from all of its runs (`reps`)."""
    # 1. Did the runs use the same evidence (e.g. the same pages)?
    same = spec.get("same")
    overlap = _overlap(reps, same) if same else None
    also = {field: _overlap(reps, field) for field in spec.get("report") or []}   # shown only, not gated
    evidence_ok = overlap is None or overlap >= float(spec.get("min_overlap", 1.0))

    # 2. Did the judges that matter pass in every run?
    passes, not_judged = _judge_outcomes(reps, spec)
    answers_ok = all(p == n for p, n in passes.values())

    # 3. Did any run fail to be evaluated at all?
    errors = sum(c.status == ERROR for c in reps)

    # The reasons, in plain words, for a person to read.
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
    """For each judge that matters: how often it passed, e.g. {"correctness": (4, 5)} = 4 of 5 runs.

    Returns (passes, not_judged). A judge that was skipped in every run can't pass or fail, so it goes
    into `not_judged` with the reason instead.
    """
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
    """anchor_page_ids -> 'anchor pages' (for people, not config)."""
    words = (field or "").removesuffix("_ids").removesuffix("_id").replace("_", " ").strip()
    return words + ("s" if words and not words.endswith("s") else "")


def _overlap(reps: list[CaseResult], field: str) -> float:
    sets = [frozenset(str(x) for x in _as_list((c.details or {}).get(field))) for c in reps]
    return min(_jaccard(a, b) for a, b in combinations(sets, 2))


def targets(run: Run) -> list[dict[str, Any]]:
    """One row per target: actual value, target, met (False when there is no data)."""
    if not run.targets:
        return []
    rates = {row["name"]: row for row in summarise([run])}      # pass rate of each judge / check
    rows = []
    for name, target in run.targets.items():
        actual, detail = _target_value(run, name, rates)
        if actual is None:
            # No data. That counts as "not met" - except `consistency` when each case ran only once,
            # because then it can't apply (met = None, and gate() ignores it).
            met = None if name == "consistency" and run.reps < 2 else False
        elif name in MAX_TARGETS:
            met = actual <= target          # a ceiling, e.g. error_rate: must stay at or below
        else:
            met = actual >= target          # a floor, e.g. correctness: must reach at least this
        rows.append({"name": name, "actual": actual, "target": target, "met": met,
                     "ceiling": name in MAX_TARGETS, "detail": detail})
    return rows


def _target_value(run: Run, name: str, rates: dict[str, dict]) -> tuple[float | None, str]:
    """What this run actually scored for one target: (value, a few words about it).

    The value is None when there is nothing to measure.
    """
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
    """(every target met, the target rows). Targets that don't apply (consistency at REPS=1) are ignored."""
    rows = targets(run)
    return all(r["met"] is not False for r in rows), rows


def _jaccard(a: frozenset, b: frozenset) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]
