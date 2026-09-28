"""
Step 8 decision rule — all configured conditions must hold to ship.

No weighted overall AI score. Safety hard-stops have no override.
"""

from __future__ import annotations

from src.comparison.models import (
    ComparisonResult,
    GateResult,
    MetricRole,
    MetricVerdict,
)


_PASSING = {
    MetricVerdict.IMPROVEMENT,
    MetricVerdict.EQUIVALENT,
    MetricVerdict.ACCEPTABLE_REGRESSION,
}


def evaluate_gate(
    result: ComparisonResult,
    *,
    require_stability: bool = True,
    require_similarity: bool = True,
    require_judge_reliability: bool = True,
    divergences_reviewed: bool = False,
) -> GateResult:
    """
    Ship only when all Step-8 conditions hold:

    1. Pipeline sound (A/A · B/B clean when required)
    2. Primary metric(s) non-inferior / acceptable
    3. Safety: zero critical events for B (configured)
    4. Similarity inside band OR divergences SME-reviewed
    5. B no less consistent than A
    6. No deciding metric gated by unreliable judge
    (+ ops budget when configured)
    """
    reasons: list[str] = []
    conditions: dict[str, bool] = {}

    # 3 — Safety
    safety_ok = all(s.passed for s in result.safety) if result.safety else True
    conditions["3 safety: zero/allowed critical events for B"] = safety_ok
    if not safety_ok:
        for s in result.safety:
            if not s.passed:
                reasons.append(
                    f"Safety hard fail: {s.metric_name} "
                    f"(B events={s.candidate_b_events}, allowed={s.allowed_events})"
                )

    # 2 — Primary + guardrails (guardrails are part of quality gate)
    primary = [
        m
        for m in result.per_metric
        if m.role == MetricRole.PRIMARY and not m.demoted_unreliable_judge
    ]
    guardrails = [
        m
        for m in result.per_metric
        if m.role == MetricRole.GUARDRAIL and not m.demoted_unreliable_judge
    ]

    primary_ok = True
    if primary:
        for m in primary:
            if m.verdict not in _PASSING:
                primary_ok = False
                reasons.append(f"Primary metric {m.metric_name}: {m.verdict.value}")
    else:
        reasons.append(
            "No primary metrics configured (or all demoted); gate cannot claim primary NI."
        )
        primary_ok = False
    conditions["2 primary metric non-inferior"] = primary_ok

    guardrails_ok = True
    for m in guardrails:
        if m.verdict not in _PASSING:
            guardrails_ok = False
            reasons.append(f"Guardrail {m.metric_name}: {m.verdict.value}")
    conditions["2b guardrails within tolerance"] = guardrails_ok

    # 1 — Stability / A/A
    stability_ok = True
    if require_stability:
        if not result.stability:
            stability_ok = False
            reasons.append("Stability required but no A/A or B/B results available.")
        else:
            stability_ok = all(s.appears_stable for s in result.stability)
            # Also fail if any tolerance is unenforceable vs resolution
            for s in result.stability:
                if s.tolerance_enforceable is False:
                    stability_ok = False
                    reasons.append(
                        f"Tolerance unenforceable on {s.arm.upper()}/{s.metric_name}: "
                        f"δ={s.margin} < resolution={s.resolution}."
                    )
            if not all(s.appears_stable for s in result.stability):
                reasons.append(
                    "A/A or B/B null test failed — harness/judge may be broken; fix before evaluating B."
                )
    conditions["1 pipeline sound (A/A clean)"] = stability_ok

    # 4 — Similarity band
    similarity_ok = True
    consistency_ok = True
    if require_similarity:
        sim = result.similarity
        if sim is None:
            similarity_ok = False
            reasons.append(
                "Similarity screen required but no answer/embedding data available."
            )
        else:
# Soften similarity gate: inside_band OR no divergents OR SME reviewed
            reviewed = divergences_reviewed or sim.divergences_reviewed
            if reviewed:
                similarity_ok = True
            elif not sim.divergent_case_ids:
                similarity_ok = True
            else:
                similarity_ok = bool(sim.inside_band)
                if not similarity_ok:
                    reasons.append(
                        f"Similarity: {len(sim.divergent_case_ids)} divergent cases below T_sim "
                        "require SME review (or set divergences_reviewed: true)."
                    )
            consistency_ok = sim.consistency_ok
            if not consistency_ok:
                reasons.append(sim.consistency_note or "B less self-consistent than A.")
    conditions["4 similarity inside band (or divergences reviewed)"] = similarity_ok
    conditions["5 B no less consistent than A"] = consistency_ok

    # 6 — Judge reliability
    judge_reliability_ok = True
    if require_judge_reliability and result.judge_variance:
        for jv in result.judge_variance:
            if jv.demoted or not jv.reliable:
                if jv.role in {MetricRole.PRIMARY, MetricRole.GUARDRAIL}:
                    judge_reliability_ok = False
                    reasons.append(
                        f"Unreliable judge on deciding metric {jv.metric_name}: {jv.note}"
                    )
    conditions["6 no metric gated by an unreliable judge"] = judge_reliability_ok

    # Ops
    ops = result.operations
    operations_ok = True
    if ops.latency_within_budget is False:
        operations_ok = False
        reasons.append("Candidate B latency p95 exceeds configured budget.")
    if ops.cost_within_budget is False:
        operations_ok = False
        reasons.append("Candidate B cost exceeds configured budget (leadership decision).")
    conditions["7 operations within budget"] = operations_ok

    acceptable = (
        safety_ok
        and primary_ok
        and guardrails_ok
        and stability_ok
        and similarity_ok
        and consistency_ok
        and judge_reliability_ok
        and operations_ok
    )
    if acceptable and not reasons:
        reasons.append("All Step-8 conditions satisfied — proceed to shadow, then canary.")

    return GateResult(
        comparison_acceptable=acceptable,
        primary_ok=primary_ok,
        guardrails_ok=guardrails_ok,
        safety_ok=safety_ok,
        stability_ok=stability_ok,
        similarity_ok=similarity_ok,
        consistency_ok=consistency_ok,
        judge_reliability_ok=judge_reliability_ok,
        operations_ok=operations_ok,
        ship=acceptable,
        conditions=conditions,
        reasons=reasons,
    )
