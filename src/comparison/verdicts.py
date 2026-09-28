"""
Map p_NI × p_diff × sign(Δ) to per-metric verdicts (document decision table).

passes = p_NI < alpha
if not passes:
    FAIL if wilcoxon_p < alpha and observed_delta < 0 else INCONCLUSIVE
elif wilcoxon_p >= alpha:
    EQUIVALENT
else:
    IMPROVEMENT if observed_delta > 0 else ACCEPTABLE_REGRESSION
"""

from __future__ import annotations

from src.comparison.models import (
    BootstrapResult,
    MetricRole,
    MetricVerdict,
    NonInferiorityResult,
    WilcoxonResult,
)
from src.comparison.statistics import non_inferiority_satisfied_from_p


def decide_metric_verdict(
    *,
    bootstrap: BootstrapResult | None,
    margin: float | None,
    role: MetricRole,
    wilcoxon: WilcoxonResult | None = None,
    alpha: float = 0.05,
    improvement_floor: float = 0.0,  # kept for API compat; unused in doc matrix
) -> tuple[MetricVerdict, NonInferiorityResult | None, str]:
    """Document-aligned verdict from inflated bootstrap p_NI + Wilcoxon p_diff."""
    _ = improvement_floor
    if bootstrap is None or bootstrap.n_pairs == 0:
        return MetricVerdict.INCONCLUSIVE, None, "No paired observations."

    observed = bootstrap.observed_mean_delta
    p_diff = wilcoxon.p_value if wilcoxon is not None else None

    if margin is None:
        if role in {MetricRole.PRIMARY, MetricRole.GUARDRAIL}:
            return (
                MetricVerdict.INCONCLUSIVE,
                None,
                "No non_inferiority_margin configured for a decision metric.",
            )
        # Diagnostic without margin: report directional CI only
        if bootstrap.one_sided_lower > 0 and observed > 0:
            return MetricVerdict.IMPROVEMENT, None, "Diagnostic: lower bound > 0."
        if bootstrap.ci_high < 0:
            return MetricVerdict.FAIL, None, "Diagnostic: CI entirely below 0."
        return MetricVerdict.INCONCLUSIVE, None, "Diagnostic: no margin; not decisive."

    m = abs(margin)
    p_ni = bootstrap.p_ni
    if p_ni is None:
        # Recompute satisfaction from lower bound if p_ni missing
        from src.comparison.statistics import non_inferiority_satisfied

        ok = non_inferiority_satisfied(bootstrap.one_sided_lower, m)
        p_ni = 0.0 if ok else 1.0

    passes = non_inferiority_satisfied_from_p(p_ni, alpha=alpha)
    ni = NonInferiorityResult(
        margin=m,
        one_sided_lower=bootstrap.one_sided_lower,
        satisfied=passes,
        p_ni=p_ni,
    )

    # Missing Wilcoxon → treat as non-significant difference (conservative for improvement claims)
    wilcoxon_sig = p_diff is not None and p_diff < alpha
    wilcoxon_ns = p_diff is None or p_diff >= alpha

    if not passes:
        if wilcoxon_sig and observed < 0:
            return (
                MetricVerdict.FAIL,
                ni,
                f"p_NI={p_ni:.4f}≥{alpha}; p_diff={p_diff:.4f}<{alpha}; Δ<0 → FAIL.",
            )
        return (
            MetricVerdict.INCONCLUSIVE,
            ni,
            f"p_NI={p_ni:.4f}≥{alpha}; could not establish non-inferiority (absence of evidence).",
        )

    if wilcoxon_ns:
        return (
            MetricVerdict.EQUIVALENT,
            ni,
            f"p_NI={p_ni:.4f}<{alpha}; no detectable change (p_diff≥{alpha}).",
        )

    if observed > 0:
        return (
            MetricVerdict.IMPROVEMENT,
            ni,
            f"p_NI={p_ni:.4f}<{alpha}; p_diff={p_diff:.4f}<{alpha}; Δ>0 → IMPROVEMENT.",
        )
    return (
        MetricVerdict.ACCEPTABLE_REGRESSION,
        ni,
        f"p_NI={p_ni:.4f}<{alpha}; p_diff={p_diff:.4f}<{alpha}; Δ≤0 → ACCEPTABLE_REGRESSION.",
    )
