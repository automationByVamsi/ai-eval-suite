"""
Paired aggregation and descriptive A/B helpers.

Positive oriented_delta always means Candidate B is better for that metric.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.comparison.models import (
    CaseDelta,
    MetricDirection,
    PairedObservation,
    RunObservation,
    WinTieLoss,
)


def orientation_sign(direction: MetricDirection) -> float:
    """+1 for larger-is-better, -1 for smaller-is-better."""
    if direction == MetricDirection.SMALLER_IS_BETTER:
        return -1.0
    return 1.0


def oriented_delta(
    a: float,
    b: float,
    direction: MetricDirection,
) -> float:
    """Return orient(B - A) so positive means B better."""
    return orientation_sign(direction) * (b - a)


def mean(values: list[float]) -> float | None:
    """Arithmetic mean, or None if empty."""
    if not values:
        return None
    return sum(values) / len(values)


def percentile(sorted_values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile; ``p`` in [0, 100]."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    p = max(0.0, min(100.0, p))
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def median(values: list[float]) -> float | None:
    """Median of unsorted values."""
    if not values:
        return None
    return percentile(sorted(values), 50.0)


def p95(values: list[float]) -> float | None:
    """95th percentile of unsorted values."""
    if not values:
        return None
    return percentile(sorted(values), 95.0)


def pair_observations(
    observations: Iterable[RunObservation],
    metric_name: str,
    direction: MetricDirection,
) -> list[PairedObservation]:
    """
    Build per-test-case paired means for one metric.

    A_i = mean(A runs for case i); B_i = mean(B runs for case i).
    Missing arm → ``missing=True`` and no oriented_delta.
    """
    a_runs: dict[str, list[float]] = defaultdict(list)
    b_runs: dict[str, list[float]] = defaultdict(list)

    for obs in observations:
        if obs.metric_name != metric_name or obs.score is None:
            continue
        if obs.candidate == "a":
            a_runs[obs.test_case_id].append(float(obs.score))
        elif obs.candidate == "b":
            b_runs[obs.test_case_id].append(float(obs.score))

    case_ids = sorted(set(a_runs) | set(b_runs))
    paired: list[PairedObservation] = []
    for case_id in case_ids:
        a_list = a_runs.get(case_id, [])
        b_list = b_runs.get(case_id, [])
        a_mean = mean(a_list)
        b_mean = mean(b_list)
        missing = a_mean is None or b_mean is None
        delta = None if missing else oriented_delta(a_mean, b_mean, direction)
        paired.append(
            PairedObservation(
                test_case_id=case_id,
                metric_name=metric_name,
                candidate_a_runs=list(a_list),
                candidate_b_runs=list(b_list),
                candidate_a_mean=a_mean,
                candidate_b_mean=b_mean,
                oriented_delta=delta,
                missing=missing,
            )
        )
    return paired


def complete_deltas(paired: list[PairedObservation]) -> list[float]:
    """Oriented deltas for cases present on both arms."""
    return [
        p.oriented_delta
        for p in paired
        if not p.missing and p.oriented_delta is not None
    ]


def win_tie_loss(
    paired: list[PairedObservation],
    *,
    epsilon: float,
) -> WinTieLoss:
    """
    Count B-better / tie / A-better using |oriented_delta| <= epsilon as tie.

    Diagnostic only — not a release decision.
    """
    wtl = WinTieLoss(epsilon=epsilon)
    for p in paired:
        if p.missing or p.oriented_delta is None:
            continue
        d = p.oriented_delta
        if abs(d) <= epsilon:
            wtl.tie += 1
        elif d > 0:
            wtl.b_better += 1
        else:
            wtl.a_better += 1
    return wtl


def top_case_deltas(
    paired: list[PairedObservation],
    *,
    n: int = 5,
    regressions: bool = True,
) -> list[CaseDelta]:
    """Top regressions (most negative oriented Δ) or improvements (most positive)."""
    rows: list[CaseDelta] = []
    for p in paired:
        if (
            p.missing
            or p.oriented_delta is None
            or p.candidate_a_mean is None
            or p.candidate_b_mean is None
        ):
            continue
        rows.append(
            CaseDelta(
                test_case_id=p.test_case_id,
                candidate_a_mean=p.candidate_a_mean,
                candidate_b_mean=p.candidate_b_mean,
                oriented_delta=p.oriented_delta,
            )
        )
    rows.sort(key=lambda r: r.oriented_delta)
    if regressions:
        return [r for r in rows if r.oriented_delta < 0][:n]
    rows.sort(key=lambda r: r.oriented_delta, reverse=True)
    return [r for r in rows if r.oriented_delta > 0][:n]


def share_of(
    paired: list[PairedObservation],
    *,
    epsilon: float,
    degraded: bool,
) -> float | None:
    """Fraction of complete pairs with degradation or improvement beyond epsilon."""
    complete = [p for p in paired if not p.missing and p.oriented_delta is not None]
    if not complete:
        return None
    if degraded:
        count = sum(1 for p in complete if p.oriented_delta < -epsilon)
    else:
        count = sum(1 for p in complete if p.oriented_delta > epsilon)
    return count / len(complete)


def metric_names_from_observations(observations: Iterable[RunObservation]) -> list[str]:
    """Sorted unique metric names with at least one numeric score."""
    names = {o.metric_name for o in observations if o.score is not None}
    return sorted(names)
