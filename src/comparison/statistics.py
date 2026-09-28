"""
Paired statistical helpers aligned to the Hive A/B methodology.

Primary gate: inflated paired bootstrap → p_NI (share of Δ* ≤ −δ).
Supporting: Wilcoxon signed-rank → p_diff.
Binary path: McNemar (exact binomial on discordant pairs).
"""

from __future__ import annotations

import math
import random
from typing import Sequence

from src.comparison.models import BootstrapResult, McNemarResult, WilcoxonResult
from src.comparison.pairwise import mean


def paired_bootstrap(
    deltas: Sequence[float],
    *,
    n_bootstrap: int = 10_000,
    confidence_level: float = 0.95,
    seed: int = 42,
    inflation: float = 0.10,
    alpha: float = 0.05,
    margin: float | None = None,
) -> BootstrapResult:
    """
    Resample paired deltas; optionally inflate; return CI + p_NI.

    Conservatism (document Step 7.3):
      boot_c = observed + (1 + inflation) * (boot - observed)
    applied ONCE before reading quantiles / p_NI.

    p_NI = share of inflated bootstrap means where Δ* ≤ −margin
    (requires ``margin``; otherwise p_ni is None).
    """
    values = [float(d) for d in deltas]
    n = len(values)
    if n == 0:
        return BootstrapResult(
            observed_mean_delta=0.0,
            ci_low=0.0,
            ci_high=0.0,
            one_sided_lower=0.0,
            n_pairs=0,
            n_bootstrap=n_bootstrap,
            seed=seed,
            inflation=inflation,
            p_ni=None,
        )

    observed = mean(values)
    assert observed is not None

    rng = random.Random(seed)
    raw_means: list[float] = []
    for _ in range(n_bootstrap):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        m = mean(sample)
        assert m is not None
        raw_means.append(m)

    # Inflate around the observed mean (widens the lower arm conservatively).
    factor = 1.0 + max(0.0, inflation)
    inflated = [observed + factor * (b - observed) for b in raw_means]
    inflated.sort()

    # Two-sided CI from inflated distribution
    alpha_two = 1.0 - confidence_level
    low_idx = int(math.floor(alpha_two / 2.0 * n_bootstrap))
    high_idx = int(math.ceil((1.0 - alpha_two / 2.0) * n_bootstrap)) - 1
    low_idx = max(0, min(n_bootstrap - 1, low_idx))
    high_idx = max(0, min(n_bootstrap - 1, high_idx))

    # One-sided lower at alpha (document: 100*alpha-th percentile)
    one_idx = int(math.floor(alpha * n_bootstrap))
    one_idx = max(0, min(n_bootstrap - 1, one_idx))
    one_sided_lower = inflated[one_idx]

    p_ni: float | None = None
    if margin is not None:
        thr = -abs(margin)
        p_ni = sum(1 for b in inflated if b <= thr) / float(n_bootstrap)

    return BootstrapResult(
        observed_mean_delta=observed,
        ci_low=inflated[low_idx],
        ci_high=inflated[high_idx],
        one_sided_lower=one_sided_lower,
        n_pairs=n,
        n_bootstrap=n_bootstrap,
        seed=seed,
        inflation=inflation,
        p_ni=p_ni,
    )


def non_inferiority_satisfied_from_p(
    p_ni: float | None,
    *,
    alpha: float = 0.05,
) -> bool:
    """Document gate: pass when p_NI < alpha (reject H0: Δ ≤ −δ)."""
    if p_ni is None:
        return False
    return p_ni < alpha


def non_inferiority_satisfied(
    one_sided_lower: float,
    margin: float,
) -> bool:
    """Legacy CI form: lower bound > −margin (equivalent without needing p_ni)."""
    return one_sided_lower > -abs(margin)


def wilcoxon_signed_rank(
    deltas: Sequence[float],
    *,
    zero_tol: float = 1e-12,
) -> WilcoxonResult:
    """
    Two-sided Wilcoxon signed-rank → p_diff (normal approximation).

    Handles all-zero differences. p > alpha must NOT be read as equivalence alone.
    """
    nonzero = [float(d) for d in deltas if abs(float(d)) > zero_tol]
    n = len(nonzero)
    if n == 0:
        return WilcoxonResult(
            statistic=0.0,
            p_value=1.0,
            n_nonzero=0,
            note="All paired differences are effectively zero.",
        )
    if n < 10:
        # Exact enumeration for small n
        return _wilcoxon_exact(nonzero)

    abs_vals = [abs(d) for d in nonzero]
    order = sorted(range(n), key=lambda i: abs_vals[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs_vals[order[j + 1]] == abs_vals[order[i]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    w_plus = sum(ranks[i] for i in range(n) if nonzero[i] > 0)
    mu = n * (n + 1) / 4.0
    sigma2 = n * (n + 1) * (2 * n + 1) / 24.0
    from collections import Counter

    tie_counts = Counter(abs_vals)
    tie_adj = sum(t * t * t - t for t in tie_counts.values()) / 48.0
    sigma2 -= tie_adj
    if sigma2 <= 0:
        return WilcoxonResult(
            statistic=w_plus,
            p_value=None,
            n_nonzero=n,
            note="Wilcoxon variance collapsed after tie correction.",
        )
    sigma = math.sqrt(sigma2)
    if w_plus > mu:
        z = (w_plus - mu - 0.5) / sigma
    elif w_plus < mu:
        z = (w_plus - mu + 0.5) / sigma
    else:
        z = 0.0
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    p = max(0.0, min(1.0, p))
    return WilcoxonResult(
        statistic=w_plus,
        p_value=p,
        n_nonzero=n,
        note="p_diff supporting test — do not treat p>alpha as equivalence alone.",
    )


def _wilcoxon_exact(nonzero: list[float]) -> WilcoxonResult:
    """Exact two-sided Wilcoxon for small n (<10) via sign enumeration."""
    n = len(nonzero)
    abs_vals = [abs(d) for d in nonzero]
    order = sorted(range(n), key=lambda i: abs_vals[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs_vals[order[j + 1]] == abs_vals[order[i]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    w_obs = sum(ranks[i] for i in range(n) if nonzero[i] > 0)
    # Enumerate all 2^n sign assignments
    total = 1 << n
    extreme = 0
    for mask in range(total):
        w = 0.0
        for bit in range(n):
            if mask & (1 << bit):
                w += ranks[bit]
        # two-sided: as or more extreme than observed from mean
        mu = n * (n + 1) / 4.0
        if abs(w - mu) >= abs(w_obs - mu) - 1e-12:
            extreme += 1
    p = extreme / total
    return WilcoxonResult(
        statistic=w_obs,
        p_value=p,
        n_nonzero=n,
        note="Exact Wilcoxon (n<10).",
    )


def mcnemar_test(
    a_pass: Sequence[bool],
    b_pass: Sequence[bool],
) -> McNemarResult:
    """
    McNemar mid-p / exact binomial on discordant pairs (binary pass/fail).

    b01 = A fail, B pass; b10 = A pass, B fail.
    """
    if len(a_pass) != len(b_pass):
        raise ValueError("a_pass and b_pass must have the same length")
    b01 = b10 = 0
    for a, b in zip(a_pass, b_pass, strict=True):
        if (not a) and b:
            b01 += 1
        elif a and (not b):
            b10 += 1
    discordant = b01 + b10
    if discordant == 0:
        return McNemarResult(
            b01=b01,
            b10=b10,
            n_discordant=0,
            p_value=1.0,
            note="No discordant pairs.",
        )
    # Exact two-sided binomial under p=0.5
    # P(|X - n/2| >= |b01 - n/2|) with X~Bin(n, 0.5)
    n = discordant
    k = b01
    # two-sided: sum Binom for outcomes as extreme as k
    dist_from_half = abs(k - n / 2.0)
    p = 0.0
    for x in range(n + 1):
        if abs(x - n / 2.0) >= dist_from_half - 1e-12:
            p += _binom_pmf(n, x, 0.5)
    p = min(1.0, max(0.0, p))
    return McNemarResult(
        b01=b01,
        b10=b10,
        n_discordant=discordant,
        p_value=p,
        note="McNemar exact two-sided on discordant pairs.",
    )


def _binom_pmf(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p**k) * ((1 - p) ** (n - k))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def split_half_deltas(
    a_runs_by_case: dict[str, list[float]],
    *,
    direction_sign: float = 1.0,
) -> list[float]:
    """A' vs A'' oriented deltas by splitting runs per case in half."""
    deltas: list[float] = []
    for _case_id, runs in sorted(a_runs_by_case.items()):
        if len(runs) < 2:
            continue
        mid = len(runs) // 2
        first = runs[:mid]
        second = runs[mid:]
        if not first or not second:
            continue
        m1 = sum(first) / len(first)
        m2 = sum(second) / len(second)
        deltas.append(direction_sign * (m2 - m1))
    return deltas


def aa_resolution_half_width(bootstrap: BootstrapResult) -> float:
    """Half-width of two-sided CI — document 'A/A resolution' proxy."""
    return 0.5 * abs(bootstrap.ci_high - bootstrap.ci_low)


def tolerance_enforceable(resolution: float, margin: float) -> bool:
    """δ tighter than A/A resolution is unenforceable."""
    return abs(margin) >= resolution - 1e-12
