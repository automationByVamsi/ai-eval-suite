"""Safety hard gates — never cancelled by quality improvements elsewhere."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.comparison.models import RunObservation, SafetyMetricResult


def rule_of_three_upper_bound(n_trials: int) -> float | None:
    """
    If zero events in n independent trials, ≈95% upper bound on event rate ≈ 3/n.

    Diagnostic only — not fake certainty.
    """
    if n_trials <= 0:
        return None
    return 3.0 / float(n_trials)


def evaluate_safety_metric(
    observations: Iterable[RunObservation],
    *,
    metric_name: str,
    allowed_events: int = 0,
    critical: bool = True,
) -> SafetyMetricResult:
    """Count critical events per candidate for one safety metric."""
    a_events = 0
    b_events = 0
    b_trials = 0
    for obs in observations:
        if obs.metric_name != metric_name:
            continue
        # Prefer explicit critical_event; else treat passed=False as an event.
        is_event = bool(obs.critical_event) or (obs.passed is False)

        if obs.candidate == "a":
            if is_event:
                a_events += 1
        elif obs.candidate == "b":
            b_trials += 1
            if is_event:
                b_events += 1

    passed = b_events <= allowed_events
    ub = None
    note = ""
    if b_events == 0 and b_trials > 0:
        ub = rule_of_three_upper_bound(b_trials)
        note = (
            f"Zero Candidate B events in {b_trials} trials; "
            f"≈95% rule-of-three upper bound ≈ {ub:.4f} ({ub:.2%})."
        )
    elif not passed:
        note = (
            f"Candidate B critical events={b_events} exceeds allowed_events={allowed_events}."
        )

    return SafetyMetricResult(
        metric_name=metric_name,
        candidate_a_events=a_events,
        candidate_b_events=b_events,
        allowed_events=allowed_events,
        critical=critical,
        passed=passed if critical else True,
        rule_of_three_upper_bound=ub,
        n_trials_b=b_trials,
        note=note,
    )


def group_critical_flags(
    observations: Iterable[RunObservation],
) -> dict[str, dict[str, int]]:
    """metric → {a: count, b: count} for explicit critical_event flags."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"a": 0, "b": 0})
    for obs in observations:
        if not obs.critical_event:
            continue
        if obs.candidate in {"a", "b"}:
            counts[obs.metric_name][obs.candidate] += 1
    return dict(counts)
