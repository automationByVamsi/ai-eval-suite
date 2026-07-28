"""Human-readable VERDICT tables for the terminal."""

from __future__ import annotations

from src.verdict.models import VerdictReport


def _pct(rate: float) -> str:
    """Format a decimal rate as a right-aligned percentage."""
    return f"{rate * 100:5.1f}%"


def print_report(report: VerdictReport) -> None:
    """Print a readable terminal summary for a VERDICT report."""
    print("\n" + "=" * 72)
    print("VERDICT — reliability report")
    print("=" * 72)
    print(
        f"profile={report.profile}  tag={report.tag}  "
        f"N={report.n_reps}  judges={'on' if report.run_judges else 'off'}  "
        f"simulate_regression={report.simulate_regression}"
    )

    print("\n--- What a single-run board would say ---")
    # Collapse to case×stage using first-rep-style: all-pass if pass_rate==1
    seen: set[tuple[str, str]] = set()
    for agg in report.aggregates:
        key = (agg.test_case_id, agg.stage)
        if key in seen:
            continue
        seen.add(key)
        stage_aggs = [
            a for a in report.aggregates if a.test_case_id == agg.test_case_id and a.stage == agg.stage
        ]
        # Single-run illusion: if every check has pass_rate > 0, a lucky rep can look green.
        any_always_fail = any(a.pass_rate <= 0.0 for a in stage_aggs)
        any_flaky = any(0.0 < a.pass_rate < 1.0 for a in stage_aggs)
        if any_always_fail:
            label = "FAIL"
        elif any_flaky:
            label = "PASS*"  # lucky single sample could still pass
        else:
            label = "PASS"
        note = "  ← hides flakiness" if label == "PASS*" else ""
        print(f"  [{label}] {agg.test_case_id} :: {agg.stage}{note}")

    print("\n--- Distributions (honest picture) ---")
    print(f"  {'case':7} {'stage':22} {'check':28} {'kind':13} {'pass_rate':>9}  score")
    print("  " + "-" * 90)
    for a in report.aggregates:
        score_bit = ""
        if a.mean_score is not None:
            std = a.std_score or 0.0
            score_bit = f"  {a.mean_score:.2f}±{std:.2f}"
        flaky = "  ⚠ flaky" if 0.0 < a.pass_rate < 1.0 else ""
        print(
            f"  {a.test_case_id:7} {a.stage:22} {a.name:28} {a.kind:13} "
            f"{_pct(a.pass_rate):>9}{score_bit}{flaky}"
        )

    if report.diffs:
        print("\n--- vs baseline ---")
        print(
            f"  {'case':7} {'stage':22} {'check':28} "
            f"{'baseline':>9} {'current':>9} {'delta':>8}  status"
        )
        print("  " + "-" * 100)
        for d in report.diffs:
            mark = ""
            if d.status == "regression":
                mark = "  🔴 REGRESSION"
            elif d.status == "improved":
                mark = "  ✓ improved"
            print(
                f"  {d.test_case_id:7} {d.stage:22} {d.name:28} "
                f"{_pct(d.baseline_pass_rate):>9} {_pct(d.current_pass_rate):>9} "
                f"{d.delta * 100:+7.1f}pp{mark}"
            )

    print("\n--- Gate ---")
    if report.has_regression:
        print("  VERDICT: FAIL — stage metric(s) regressed vs baseline beyond noise band")
    elif not report.single_run_all_passed and not any(
        0.0 < a.pass_rate < 1.0 for a in report.aggregates
    ):
        print("  VERDICT: FAIL — hard failures on every repetition")
    else:
        print("  VERDICT: OK — no regression beyond drop threshold")
        if any(0.0 < a.pass_rate < 1.0 for a in report.aggregates):
            print("  note: some checks are flaky across reps (single-run PASS would hide this)")
    print("=" * 72 + "\n")
