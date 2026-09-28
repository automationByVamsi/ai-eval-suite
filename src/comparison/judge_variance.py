"""
Judge reliability: σ_judge vs σ_gen.

When the same output is rescored multiple times (``judge_rescores``),
estimate judge variance. Generation variance comes from run-to-run score
spread on the same case. Metrics where σ_judge ≥ σ_gen should be demoted
to diagnostic (document Step 3 / Step 8 condition 6).
"""

from __future__ import annotations

import math
from collections import defaultdict

from src.comparison.models import JudgeVarianceResult, MetricRole, RunObservation


def estimate_judge_variance(
    observations: list[RunObservation],
    *,
    metric_name: str,
    role: MetricRole = MetricRole.DIAGNOSTIC,
) -> JudgeVarianceResult | None:
    """
    Compare judge re-score SD to generation (rep) SD for one metric.

    Uses Candidate A observations primarily (baseline ruler).
    """
    # Generation variance: across reps per case (arm a)
    gen_sds: list[float] = []
    by_case: dict[str, list[float]] = defaultdict(list)
    judge_sds: list[float] = []

    for obs in observations:
        if obs.metric_name != metric_name or obs.candidate != "a":
            continue
        if obs.score is not None:
            by_case[obs.test_case_id].append(float(obs.score))
        if obs.judge_rescores and len(obs.judge_rescores) >= 2:
            judge_sds.append(_sample_sd([float(x) for x in obs.judge_rescores]))

    for scores in by_case.values():
        if len(scores) >= 2:
            gen_sds.append(_sample_sd(scores))

    if not gen_sds and not judge_sds:
        return None

    sigma_gen = mean_or_none(gen_sds)
    sigma_judge = mean_or_none(judge_sds)

    # If no rescored data, assume judge is fine (cannot prove unreliability)
    if sigma_judge is None:
        return JudgeVarianceResult(
            metric_name=metric_name,
            role=role,
            sigma_judge=None,
            sigma_gen=sigma_gen,
            reliable=True,
            demoted=False,
            note="No judge_rescores provided; cannot estimate σ_judge.",
        )

    if sigma_gen is None or sigma_gen <= 0:
        reliable = True
        demoted = False
        note = "σ_gen unavailable; σ_judge estimated but not demoted."
    else:
        reliable = sigma_judge < sigma_gen
        demoted = not reliable and role in {MetricRole.PRIMARY, MetricRole.GUARDRAIL}
        note = (
            f"σ_judge={sigma_judge:.4f} {'<' if reliable else '≥'} σ_gen={sigma_gen:.4f}. "
            + ("OK." if reliable else "Demote to diagnostic / fix judge.")
        )

    return JudgeVarianceResult(
        metric_name=metric_name,
        role=role,
        sigma_judge=sigma_judge,
        sigma_gen=sigma_gen,
        reliable=reliable,
        demoted=demoted,
        note=note,
    )


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sample_sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)
