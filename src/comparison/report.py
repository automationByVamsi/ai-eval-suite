"""Terminal + JSON reporting for ComparisonResult."""

from __future__ import annotations

from pathlib import Path

from src.comparison.models import ComparisonResult, MetricVerdict


def write_comparison_json(result: ComparisonResult, path: str | Path) -> Path:
    """Persist machine-readable ComparisonResult."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return p


def print_comparison_report(result: ComparisonResult) -> None:
    """Human-readable comparative summary (no overall AI score)."""
    print("\n" + "=" * 78)
    print("A/B COMPARATIVE EVALUATION")
    print("=" * 78)
    print(f"Experiment:   {result.experiment_name}")
    if result.description:
        print(f"Description:  {result.description}")
    print(f"Dimension:    {result.dimension.value}")
    print(f"Candidate A:  {result.candidate_a.name} (agent={result.candidate_a.agent})")
    print(f"Candidate B:  {result.candidate_b.name} (agent={result.candidate_b.agent})")
    print(f"Dataset:      {result.dataset_agent}/{result.dataset_suite}")
    print(f"Eval suite:   {result.evaluation_suite}")
    print(f"Repetitions:  {result.repetitions}")
    print(f"Mode:         {result.mode}")

    if result.warnings:
        print("\n--- Warnings ---")
        for w in result.warnings:
            print(f"  ! {w}")

    print("\n--- Metric summary ---")
    print(
        f"  {'Metric':22} {'A':>7} {'B':>7} {'Delta':>8} "
        f"{'p_NI':>8} {'p_diff':>8} {'Verdict':>22}"
    )
    print("  " + "-" * 100)
    for m in result.per_metric:
        a = _fmt(m.candidate_a_mean)
        b = _fmt(m.candidate_b_mean)
        d = _fmt(m.observed_delta, signed=True)
        p_ni = (
            f"{m.non_inferiority.p_ni:.4f}"
            if m.non_inferiority and m.non_inferiority.p_ni is not None
            else "n/a"
        )
        p_diff = (
            f"{m.wilcoxon.p_value:.4f}"
            if m.wilcoxon and m.wilcoxon.p_value is not None
            else "n/a"
        )
        mark = _verdict_mark(m.verdict)
        print(
            f"  {m.metric_name:22} {a:>7} {b:>7} {d:>8} "
            f"{p_ni:>8} {p_diff:>8} {mark}{m.verdict.value}"
        )
        if m.bootstrap:
            print(
                f"    CI95=[{m.bootstrap.ci_low:+.4f},{m.bootstrap.ci_high:+.4f}] "
                f"lower1s={m.bootstrap.one_sided_lower:+.4f} "
                f"inflation={m.bootstrap.inflation}"
            )
        if m.win_tie_loss:
            w = m.win_tie_loss
            print(
                f"    win/tie/loss (eps={w.epsilon}): "
                f"B={w.b_better}  tie={w.tie}  A={w.a_better}"
            )
        if m.degraded_case_share is not None:
            print(f"    degraded_share={m.degraded_case_share:.2%}")

    if result.safety:
        print("\n--- Safety (count, don't average) ---")
        for s in result.safety:
            status = "PASS" if s.passed else "HARD FAIL"
            print(
                f"  [{status}] {s.metric_name}: "
                f"A_events={s.candidate_a_events} B_events={s.candidate_b_events} "
                f"allowed={s.allowed_events}"
            )
            if s.note:
                print(f"    {s.note}")

    if result.stability:
        print("\n--- Stability (A/A · B/B) ---")
        for s in result.stability:
            label = "stable" if s.appears_stable else "UNSTABLE"
            res = f" resolution={s.resolution:.4f}" if s.resolution is not None else ""
            print(
                f"  [{label}] {s.arm.upper()}/{s.metric_name} "
                f"meanΔ={s.observed_mean_delta:+.4f} "
                f"CI=[{s.ci_low:+.4f},{s.ci_high:+.4f}] n={s.n_pairs}{res}"
            )
            if s.note:
                print(f"    {s.note}")

    if result.similarity:
        sim = result.similarity
        print("\n--- Similarity screen (triage) ---")
        print(
            f"  S_AA={_fmt(sim.s_aa_mean)}±{_fmt(sim.s_aa_std)}  "
            f"S_BB={_fmt(sim.s_bb_mean)}±{_fmt(sim.s_bb_std)}  "
            f"S_AB={_fmt(sim.s_ab_mean)}±{_fmt(sim.s_ab_std)}"
        )
        print(
            f"  T_sim(5th of S_AA)={_fmt(sim.t_sim)}  "
            f"inside_band={sim.inside_band}  consistency_ok={sim.consistency_ok}"
        )
        print(f"  method={sim.method}  {sim.note}")
        if sim.divergent_case_ids:
            print(f"  divergent (first 20): {sim.divergent_case_ids[:20]}")

    if result.judge_variance:
        print("\n--- Judge reliability (σ_judge vs σ_gen) ---")
        for jv in result.judge_variance:
            print(
                f"  {jv.metric_name}: σ_judge={_fmt(jv.sigma_judge)} "
                f"σ_gen={_fmt(jv.sigma_gen)} reliable={jv.reliable} demoted={jv.demoted}"
            )
            if jv.note:
                print(f"    {jv.note}")

    ops = result.operations
    print("\n--- Operations ---")
    print(
        f"  Latency A: median={_fmt(ops.candidate_a_latency_median_ms)} ms  "
        f"p95={_fmt(ops.candidate_a_latency_p95_ms)} ms"
    )
    print(
        f"  Latency B: median={_fmt(ops.candidate_b_latency_median_ms)} ms  "
        f"p95={_fmt(ops.candidate_b_latency_p95_ms)} ms"
    )
    print(f"  Cost: {ops.cost_note}")
    if ops.latency_within_budget is not None:
        print(f"  latency_within_budget={ops.latency_within_budget}")
    if ops.cost_within_budget is not None:
        print(f"  cost_within_budget={ops.cost_within_budget}")

    print("\n--- Top regressions ---")
    any_reg = False
    for m in result.per_metric:
        if not m.top_regressions:
            continue
        any_reg = True
        print(f"  {m.metric_name}:")
        for row in m.top_regressions:
            print(
                f"    {row.test_case_id}: A={row.candidate_a_mean:.3f} "
                f"B={row.candidate_b_mean:.3f} Δ={row.oriented_delta:+.3f}"
            )
    if not any_reg:
        print("  (none)")

    print("\n--- Top improvements ---")
    any_imp = False
    for m in result.per_metric:
        if not m.top_improvements:
            continue
        any_imp = True
        print(f"  {m.metric_name}:")
        for row in m.top_improvements:
            print(
                f"    {row.test_case_id}: A={row.candidate_a_mean:.3f} "
                f"B={row.candidate_b_mean:.3f} Δ={row.oriented_delta:+.3f}"
            )
    if not any_imp:
        print("  (none)")

    print("\n--- Step 8 gate ---")
    if result.gate:
        g = result.gate
        status = "SHIP (shadow→canary)" if g.ship else "DO NOT SHIP"
        print(f"  comparison_acceptable = {g.comparison_acceptable}  [{status}]")
        for label, ok in g.conditions.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        for reason in g.reasons:
            print(f"  - {reason}")
    else:
        print("  (no gate computed)")
    print("=" * 78 + "\n")


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if signed:
        return f"{value:+.3f}"
    return f"{value:.3f}"


def _verdict_mark(verdict: MetricVerdict) -> str:
    if verdict == MetricVerdict.IMPROVEMENT:
        return "✓ "
    if verdict == MetricVerdict.FAIL:
        return "✗ "
    if verdict == MetricVerdict.INCONCLUSIVE:
        return "? "
    return "  "
