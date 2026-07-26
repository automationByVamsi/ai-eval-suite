"""
Run existing Knowledge Agent stage contracts many times and aggregate.

Expects ADK outputs already under outputs/traces (capture live via run_case /
scripts.capture_traces first). Re-running judges N times surfaces judge noise.
--simulate-regression injects a DAFAT-style upstream drop so baseline diff
is visible without a live broken build.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.models.evaluation_result import DeterministicCheckResult
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.verdict.aggregate import aggregate_reps
from src.verdict.baseline import load_baseline, save_baseline
from src.verdict.diff import diff_against_baseline
from src.verdict.models import CheckObservation, RepResult, VerdictReport
from src.verdict.report import print_report
from tests.knowledge_agent import stage1_contract, stage2_contract
from tests.knowledge_agent.base import KnowledgeAgentTest


# Metrics that "break" in simulate-regression (upstream expansion-style drop).
_SIM_FAIL_CHECKS = {
    "stage1_query_rewrite": {"result_count_positive", "query_optimization"},
    "stage2_anchor_node": {"anchor_accuracy", "anchor_relevance"},
}


class _VerdictHarness(KnowledgeAgentTest):
    """Reuse KA parse/judge helpers without pytest fixtures."""

    tag = "sanity"


def _to_obs_det(results: list[DeterministicCheckResult]) -> list[CheckObservation]:
    return [
        CheckObservation(name=r.name, kind="deterministic", passed=r.passed, reason=r.reason)
        for r in results
    ]


def _to_obs_judge(results: list[MetricResult]) -> list[CheckObservation]:
    return [
        CheckObservation(
            name=r.name,
            kind="judge",
            passed=r.passed,
            score=r.score,
            threshold=r.threshold,
            reason=r.reason,
        )
        for r in results
    ]


def _inject_regression(
    checks: list[CheckObservation],
    *,
    stage: str,
    rep: int,
    n_reps: int,
) -> list[CheckObservation]:
    """
    Fail selected checks on the majority of reps (ceil(60%)).

    Mimics a build where companion-page / candidate quality drops most of
    the time, while a lucky single sample can still look fine.
    """
    fail_names = _SIM_FAIL_CHECKS.get(stage, set())
    if not fail_names:
        return checks
    # Fail on reps after the first lucky one when N>=3; always fail majority.
    fail_this_rep = rep >= max(1, n_reps // 5)  # ~80% of reps when N=5
    if not fail_this_rep:
        return checks

    out: list[CheckObservation] = []
    for c in checks:
        if c.name in fail_names:
            out.append(
                c.model_copy(
                    update={
                        "passed": False,
                        "score": 0.35 if c.score is not None else None,
                        "reason": (
                            c.reason
                            or "VERDICT simulate-regression: upstream coverage drop "
                            "(companion / candidate quality)"
                        ),
                    }
                )
            )
        else:
            out.append(c)
    return out


def _eval_stage1(
    harness: _VerdictHarness,
    case: TestCase,
    *,
    run_judges: bool,
) -> tuple[list[CheckObservation], bool]:
    raw = harness.load_trace(case.test_case_id)
    parsed = harness.parse_stage1(raw)
    det = stage1_contract.run_deterministic(parsed)
    checks = _to_obs_det(det)
    if run_judges:
        response = harness.build_response(parsed)
        judges = harness.run_stage_judges(
            case, response, stage1_contract.JUDGE_METRICS, stage=stage1_contract.STAGE
        )
        checks.extend(_to_obs_judge(judges))
    return checks, all(c.passed for c in checks)


def _eval_stage2(
    harness: _VerdictHarness,
    case: TestCase,
    *,
    run_judges: bool,
) -> tuple[list[CheckObservation], bool]:
    raw = harness.load_trace(case.test_case_id)
    parsed = harness.parse_stage2(raw)
    det = stage2_contract.run_deterministic(parsed, expected=case.expected)
    checks = _to_obs_det(det)
    if run_judges:
        response = harness.build_stage2_response(parsed)
        judges = harness.run_stage_judges(
            case, response, stage2_contract.JUDGE_METRICS, stage=stage2_contract.STAGE
        )
        checks.extend(_to_obs_judge(judges))
    return checks, all(c.passed for c in checks)


_STAGE_EVAL: dict[str, Callable[..., tuple[list[CheckObservation], bool]]] = {
    stage1_contract.STAGE: _eval_stage1,
    stage2_contract.STAGE: _eval_stage2,
}


def run_verdict(
    *,
    n_reps: int = 5,
    case_ids: list[str] | None = None,
    stages: list[str] | None = None,
    run_judges: bool = False,
    simulate_regression: bool = False,
    save_as_baseline: bool = False,
    compare_baseline: bool = True,
    baseline_name: str = "latest",
    drop_threshold: float = 0.15,
    output_dir: str = "outputs/verdict",
    profile: str = "knowledge_agent",
    tag: str = "sanity",
) -> VerdictReport:
    """
    Evaluate existing sanity cases N times, aggregate, optionally diff baseline.

    Default run_judges=False keeps the demo fast (Layer-1 only).
    Pass run_judges=True to also sample CORTEX GEval variance.
    """
    harness = _VerdictHarness()
    harness.profile = profile
    harness.tag = tag
    cases = harness.load_cases()

    selected_ids = case_ids or sorted(cases.keys())
    selected_stages = stages or [stage1_contract.STAGE, stage2_contract.STAGE]

    reps: list[RepResult] = []
    for case_id in selected_ids:
        case = cases[case_id]
        for stage in selected_stages:
            eval_fn = _STAGE_EVAL[stage]
            for rep in range(n_reps):
                checks, _ = eval_fn(harness, case, run_judges=run_judges)
                if simulate_regression:
                    checks = _inject_regression(
                        checks, stage=stage, rep=rep, n_reps=n_reps
                    )
                passed = all(c.passed for c in checks)
                reps.append(
                    RepResult(
                        test_case_id=case_id,
                        stage=stage,
                        rep=rep,
                        passed=passed,
                        checks=checks,
                        simulated=simulate_regression,
                    )
                )

    aggregates = aggregate_reps(reps)

    # Single-run illusion: first rep of each case×stage
    first_keys = {(r.test_case_id, r.stage) for r in reps}
    single_ok = True
    for case_id, stage in first_keys:
        first = next(r for r in reps if r.test_case_id == case_id and r.stage == stage and r.rep == 0)
        if not first.passed:
            single_ok = False
            break
    # If simulate mode leaves rep0 lucky-pass, single_ok stays True — that's the point.

    diffs = []
    has_regression = False
    baseline_root = Path(output_dir) / "baselines"
    if compare_baseline:
        try:
            baseline = load_baseline(root=baseline_root, profile=profile, name=baseline_name)
            diffs = diff_against_baseline(aggregates, baseline, drop_threshold=drop_threshold)
            has_regression = any(d.status == "regression" for d in diffs)
        except FileNotFoundError:
            diffs = []

    if save_as_baseline:
        save_baseline(
            aggregates,
            root=baseline_root,
            profile=profile,
            name=baseline_name,
            meta={
                "n_reps": n_reps,
                "run_judges": run_judges,
                "simulate_regression": simulate_regression,
                "tag": tag,
            },
        )

    # Persist full report
    run_dir = Path(output_dir) / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    report = VerdictReport(
        profile=profile,
        tag=tag,
        n_reps=n_reps,
        run_judges=run_judges,
        simulate_regression=simulate_regression,
        aggregates=aggregates,
        diffs=diffs,
        single_run_all_passed=single_ok,
        has_regression=has_regression,
    )
    stamp = "simulated" if simulate_regression else "current"
    (run_dir / f"{profile}_{stamp}.json").write_text(report.model_dump_json(indent=2))

    print_report(report)
    return report
