"""
Pure comparison engine: observations + ComparisonSpec → ComparisonResult.

Implements document Steps 5–8 analysis path (no ADK / CORTEX).
"""

from __future__ import annotations

from collections import defaultdict

from src.comparison.gate import evaluate_gate
from src.comparison.judge_variance import estimate_judge_variance
from src.comparison.models import (
    ComparisonResult,
    ComparisonSpec,
    MetricComparison,
    MetricComparisonConfig,
    MetricRole,
    OperationalSummary,
    RunObservation,
    StabilityResult,
    WilcoxonResult,
)
from src.comparison.pairwise import (
    complete_deltas,
    mean,
    median,
    metric_names_from_observations,
    orientation_sign,
    p95,
    pair_observations,
    share_of,
    top_case_deltas,
    win_tie_loss,
)
from src.comparison.safety import evaluate_safety_metric
from src.comparison.similarity import compute_similarity_screen
from src.comparison.statistics import (
    aa_resolution_half_width,
    mcnemar_test,
    paired_bootstrap,
    split_half_deltas,
    tolerance_enforceable,
    wilcoxon_signed_rank,
)
from src.comparison.verdicts import decide_metric_verdict


def analyze_comparison(
    spec: ComparisonSpec,
    observations: list[RunObservation],
    *,
    run_stability: bool | None = None,
    top_n: int = 5,
    divergences_reviewed: bool = False,
) -> ComparisonResult:
    """Aggregate paired A/B evidence into a ComparisonResult."""
    stats = spec.statistics
    do_stability = spec.require_stability if run_stability is None else run_stability

    metric_names = metric_names_from_observations(observations)
    for obs in observations:
        if obs.critical_event and obs.metric_name not in metric_names:
            metric_names.append(obs.metric_name)
    metric_names = sorted(set(metric_names) | set(spec.metric_configs))

    # Judge variance first — may demote primary/guardrail to diagnostic
    judge_variance = []
    demoted: set[str] = set()
    for name in metric_names:
        cfg = spec.metric_configs.get(name, MetricComparisonConfig())
        if cfg.role == MetricRole.SAFETY or cfg.critical:
            continue
        jv = estimate_judge_variance(observations, metric_name=name, role=cfg.role)
        if jv is not None:
            judge_variance.append(jv)
            if jv.demoted:
                demoted.add(name)

    per_metric: list[MetricComparison] = []
    safety_results = []

    for name in metric_names:
        cfg = spec.metric_configs.get(name, MetricComparisonConfig())
        effective_role = (
            MetricRole.DIAGNOSTIC if name in demoted else cfg.role
        )

        if cfg.role == MetricRole.SAFETY or cfg.critical:
            safety_results.append(
                evaluate_safety_metric(
                    observations,
                    metric_name=name,
                    allowed_events=cfg.allowed_events,
                    critical=cfg.critical or cfg.role == MetricRole.SAFETY,
                )
            )
            continue

        if cfg.binary:
            mc = _analyse_binary_metric(
                observations, name, cfg, effective_role, stats, top_n
            )
            mc.demoted_unreliable_judge = name in demoted
            if name in demoted:
                mc.note = (mc.note + " ").strip() + "Demoted: unreliable judge."
            per_metric.append(mc)
            continue

        paired = pair_observations(observations, name, cfg.direction)
        deltas = complete_deltas(paired)
        eps = cfg.tie_epsilon if cfg.tie_epsilon is not None else stats.tie_epsilon

        bootstrap = None
        wilcoxon = None
        if deltas:
            bootstrap = paired_bootstrap(
                deltas,
                n_bootstrap=stats.bootstrap_samples,
                confidence_level=stats.confidence_level,
                seed=stats.seed,
                inflation=stats.inflation,
                alpha=stats.alpha,
                margin=cfg.non_inferiority_margin,
            )
            wilcoxon = wilcoxon_signed_rank(deltas)

        a_means = [p.candidate_a_mean for p in paired if p.candidate_a_mean is not None]
        b_means = [p.candidate_b_mean for p in paired if p.candidate_b_mean is not None]

        verdict, ni, note = decide_metric_verdict(
            bootstrap=bootstrap,
            margin=cfg.non_inferiority_margin,
            role=effective_role,
            wilcoxon=wilcoxon,
            alpha=stats.alpha,
        )

        # degraded share vs margin (heterogeneity diagnostic)
        deg_share = None
        if cfg.non_inferiority_margin is not None and paired:
            m = abs(cfg.non_inferiority_margin)
            complete = [p for p in paired if not p.missing and p.oriented_delta is not None]
            if complete:
                deg_share = sum(1 for p in complete if p.oriented_delta <= -m) / len(complete)

        wtl = win_tie_loss(paired, epsilon=eps) if paired else None
        per_metric.append(
            MetricComparison(
                metric_name=name,
                role=effective_role,
                direction=cfg.direction,
                candidate_a_mean=mean(a_means) if a_means else None,
                candidate_b_mean=mean(b_means) if b_means else None,
                observed_delta=bootstrap.observed_mean_delta if bootstrap else None,
                bootstrap=bootstrap,
                non_inferiority=ni,
                wilcoxon=wilcoxon,
                win_tie_loss=wtl,
                degraded_case_share=deg_share
                if deg_share is not None
                else share_of(paired, epsilon=eps, degraded=True),
                improved_case_share=share_of(paired, epsilon=eps, degraded=False),
                top_regressions=top_case_deltas(paired, n=top_n, regressions=True),
                top_improvements=top_case_deltas(paired, n=top_n, regressions=False),
                paired=paired,
                verdict=verdict,
                note=note,
                demoted_unreliable_judge=name in demoted,
            )
        )

    stability: list[StabilityResult] = []
    if do_stability:
        stability = _compute_stability(observations, spec)

    similarity = compute_similarity_screen(
        observations,
        consistency_tolerance=stats.similarity_consistency_tolerance,
    )
    if similarity is not None and divergences_reviewed:
        similarity.divergences_reviewed = True

    operations = _operational_summary(observations, spec)

    result = ComparisonResult(
        experiment_name=spec.name,
        description=spec.description,
        dimension=spec.dimension,
        candidate_a=spec.candidate_a,
        candidate_b=spec.candidate_b,
        dataset_agent=spec.dataset_agent,
        dataset_suite=spec.dataset_suite,
        evaluation_suite=spec.evaluation_suite,
        repetitions=spec.repetitions,
        mode=spec.mode,
        warnings=list(spec.warnings),
        per_metric=per_metric,
        safety=safety_results,
        stability=stability,
        similarity=similarity,
        judge_variance=judge_variance,
        operations=operations,
    )
    result.gate = evaluate_gate(
        result,
        require_stability=do_stability,
        require_similarity=bool(spec.require_similarity),
        require_judge_reliability=bool(spec.require_judge_reliability),
        divergences_reviewed=divergences_reviewed,
    )
    return result


def _analyse_binary_metric(
    observations: list[RunObservation],
    name: str,
    cfg: MetricComparisonConfig,
    role: MetricRole,
    stats,
    top_n: int,
) -> MetricComparison:
    """Pass-rate means + McNemar p_diff; bootstrap on pass-rate deltas when possible."""
    # Aggregate pass rate per case
    a_pass: dict[str, list[bool]] = defaultdict(list)
    b_pass: dict[str, list[bool]] = defaultdict(list)
    for obs in observations:
        if obs.metric_name != name or obs.passed is None:
            continue
        if obs.candidate == "a":
            a_pass[obs.test_case_id].append(bool(obs.passed))
        elif obs.candidate == "b":
            b_pass[obs.test_case_id].append(bool(obs.passed))

    cases = sorted(set(a_pass) & set(b_pass))
    a_rates = []
    b_rates = []
    a_bools = []
    b_bools = []
    for cid in cases:
        ar = sum(a_pass[cid]) / len(a_pass[cid])
        br = sum(b_pass[cid]) / len(b_pass[cid])
        a_rates.append(ar)
        b_rates.append(br)
        a_bools.append(ar >= 0.5)
        b_bools.append(br >= 0.5)

    sign = 1.0 if cfg.direction.value == "larger_is_better" else -1.0
    deltas = [sign * (b - a) for a, b in zip(a_rates, b_rates, strict=True)]
    bootstrap = None
    wilcoxon = None
    if deltas:
        bootstrap = paired_bootstrap(
            deltas,
            n_bootstrap=stats.bootstrap_samples,
            confidence_level=stats.confidence_level,
            seed=stats.seed,
            inflation=stats.inflation,
            alpha=stats.alpha,
            margin=cfg.non_inferiority_margin,
        )
        wilcoxon = wilcoxon_signed_rank(deltas)
    mcn = mcnemar_test(a_bools, b_bools) if cases else None
    # Prefer McNemar as p_diff for binary
    if mcn and mcn.p_value is not None:
        wilcoxon = WilcoxonResult(
            statistic=float(mcn.b01 - mcn.b10),
            p_value=mcn.p_value,
            n_nonzero=mcn.n_discordant,
            note=mcn.note,
        )

    verdict, ni, note = decide_metric_verdict(
        bootstrap=bootstrap,
        margin=cfg.non_inferiority_margin,
        role=role,
        wilcoxon=wilcoxon,
        alpha=stats.alpha,
    )
    return MetricComparison(
        metric_name=name,
        role=role,
        direction=cfg.direction,
        candidate_a_mean=mean(a_rates),
        candidate_b_mean=mean(b_rates),
        observed_delta=bootstrap.observed_mean_delta if bootstrap else None,
        bootstrap=bootstrap,
        non_inferiority=ni,
        wilcoxon=wilcoxon,
        mcnemar=mcn,
        verdict=verdict,
        note=note,
    )


def _compute_stability(
    observations: list[RunObservation],
    spec: ComparisonSpec,
) -> list[StabilityResult]:
    """A/A and B/B split-half null tests on every non-safety configured metric."""
    stats = spec.statistics
    metrics = [
        (n, c)
        for n, c in spec.metric_configs.items()
        if c.role != MetricRole.SAFETY and not c.critical and not c.binary
    ]
    if not metrics:
        names = metric_names_from_observations(observations)
        metrics = [(n, MetricComparisonConfig(role=MetricRole.PRIMARY)) for n in names[:1]]

    out: list[StabilityResult] = []
    for metric, cfg in metrics:
        sign = orientation_sign(cfg.direction)
        margin = cfg.non_inferiority_margin
        for arm in ("a", "b"):
            by_case: dict[str, list[float]] = defaultdict(list)
            for obs in observations:
                if obs.candidate != arm or obs.metric_name != metric or obs.score is None:
                    continue
                by_case[obs.test_case_id].append(float(obs.score))
            deltas = split_half_deltas(by_case, direction_sign=sign)
            if len(deltas) < 2:
                out.append(
                    StabilityResult(
                        arm=arm,
                        metric_name=metric,
                        observed_mean_delta=0.0,
                        ci_low=0.0,
                        ci_high=0.0,
                        n_pairs=len(deltas),
                        appears_stable=False,
                        note=f"Insufficient reps for {arm.upper()}/{arm.upper()} on {metric}.",
                    )
                )
                continue
            boot = paired_bootstrap(
                deltas,
                n_bootstrap=min(stats.bootstrap_samples, 2000),
                confidence_level=stats.confidence_level,
                seed=stats.seed + (0 if arm == "a" else 17),
                inflation=stats.inflation,
                alpha=stats.alpha,
                margin=margin,
            )
            resolution = aa_resolution_half_width(boot)
            enforceable = (
                tolerance_enforceable(resolution, margin) if margin is not None else None
            )
            # Stable if CI includes 0 (null) — document: no significant difference
            appears = boot.ci_low <= 0.0 <= boot.ci_high
            if margin is not None:
                # also require |mean| within margin
                appears = appears and abs(boot.observed_mean_delta) <= abs(margin)
            note = (
                f"{arm.upper()}' vs {arm.upper()}'' on {metric}: "
                + ("pipeline sound" if appears else "NULL TEST FAILED")
            )
            if enforceable is False:
                note += f"; δ={margin} tighter than resolution={resolution:.4f}"
            out.append(
                StabilityResult(
                    arm=arm,
                    metric_name=metric,
                    observed_mean_delta=boot.observed_mean_delta,
                    ci_low=boot.ci_low,
                    ci_high=boot.ci_high,
                    n_pairs=boot.n_pairs,
                    appears_stable=appears,
                    resolution=resolution,
                    margin=margin,
                    tolerance_enforceable=enforceable,
                    note=note,
                )
            )
    return out


def _operational_summary(
    observations: list[RunObservation],
    spec: ComparisonSpec,
) -> OperationalSummary:
    a_lat = [o.latency_ms for o in observations if o.candidate == "a" and o.latency_ms is not None]
    b_lat = [o.latency_ms for o in observations if o.candidate == "b" and o.latency_ms is not None]
    a_cost = [o.cost for o in observations if o.candidate == "a" and o.cost is not None]
    b_cost = [o.cost for o in observations if o.candidate == "b" and o.cost is not None]
    cost_available = bool(a_cost or b_cost)
    b_p95 = p95(b_lat)
    b_cost_mean = mean(b_cost)
    lat_ok = None
    if spec.latency_p95_budget_ms is not None and b_p95 is not None:
        lat_ok = b_p95 <= spec.latency_p95_budget_ms
    cost_ok = None
    if spec.cost_budget_per_task is not None and b_cost_mean is not None:
        cost_ok = b_cost_mean <= spec.cost_budget_per_task
    return OperationalSummary(
        candidate_a_latency_median_ms=median(a_lat),
        candidate_a_latency_p95_ms=p95(a_lat),
        candidate_b_latency_median_ms=median(b_lat),
        candidate_b_latency_p95_ms=b_p95,
        candidate_a_cost_mean=mean(a_cost),
        candidate_b_cost_mean=b_cost_mean,
        cost_available=cost_available,
        cost_note=(
            "Cost reported from observation.cost fields."
            if cost_available
            else "Cost unavailable — no token/pricing data in results."
        ),
        latency_within_budget=lat_ok,
        cost_within_budget=cost_ok,
    )
