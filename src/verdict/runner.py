"""
Run Knowledge Agent stage contracts many times and aggregate (VERDICT).

Expects ADK outputs already under outputs/traces/<agent>/<suite>/ (from
pytest test_sanity / run_case). Re-running N times surfaces flakiness;
--simulate-regression injects a DAFAT-style drop so baseline diff is visible.

Uses current helpers:
  load_cases + src.verdict.ka_stages + evaluate(...)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.runners.case_runner import load_cases
from src.runners.evaluate import evaluate
from src.verdict.aggregate import aggregate_reps
from src.verdict.baseline import load_baseline, save_baseline
from src.verdict.diff import diff_against_baseline
from src.verdict.ka_stages import prepare_stage1, prepare_stage2, resolve_trace_path
from src.verdict.models import CheckObservation, RepResult, VerdictReport
from src.verdict.report import print_report
from tests.knowledge_agent import stage1_contract, stage2_contract

# Metrics that "break" in simulate-regression (upstream expansion-style drop).
_SIM_FAIL_CHECKS = {
    "stage1_query_rewrite": {"result_count_positive", "query_optimization"},
    "stage2_anchor_node": {"anchor_accuracy", "anchor_relevance"},
}


def _to_obs_det(results: list[Any]) -> list[CheckObservation]:
    return [
        CheckObservation(name=r.name, kind="deterministic", passed=r.passed, reason=r.reason or "")
        for r in results
    ]


def _to_obs_judge(results: list[Any]) -> list[CheckObservation]:
    return [
        CheckObservation(
            name=r.name,
            kind="judge",
            passed=r.passed,
            score=getattr(r, "score", None),
            threshold=getattr(r, "threshold", None),
            reason=getattr(r, "reason", "") or "",
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
    """Fail selected checks on most reps (lucky first rep can still look green)."""
    fail_names = _SIM_FAIL_CHECKS.get(stage, set())
    if not fail_names:
        return checks
    fail_this_rep = rep >= max(1, n_reps // 5)
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
    *,
    agent: str,
    case: dict[str, Any],
    trace_path: Path,
    run_judges: bool,
) -> tuple[list[CheckObservation], bool]:
    _parsed, det, response = prepare_stage1(str(trace_path), case)
    checks = _to_obs_det(det)
    if run_judges:
        judges = evaluate(agent, stage1_contract.STAGE, case, response, publish=False)
        checks.extend(_to_obs_judge(judges.judges))
    return checks, all(c.passed for c in checks)


def _eval_stage2(
    *,
    agent: str,
    case: dict[str, Any],
    trace_path: Path,
    run_judges: bool,
) -> tuple[list[CheckObservation], bool]:
    _parsed, det, response = prepare_stage2(str(trace_path), case)
    checks = _to_obs_det(det)
    if run_judges:
        judges = evaluate(agent, stage2_contract.STAGE, case, response, publish=False)
        checks.extend(_to_obs_judge(judges.judges))
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
    traces_root: str = "outputs/traces",
) -> VerdictReport:
    """
    Evaluate existing sanity traces N times, aggregate, optionally diff baseline.

    Default run_judges=False keeps the demo fast (Layer-1 only).
    """
    cases_list = load_cases(profile, tag)
    cases = {str(c["test_case_id"]): c for c in cases_list}

    selected_ids = case_ids or sorted(cases.keys())
    selected_stages = stages or [stage1_contract.STAGE, stage2_contract.STAGE]

    reps: list[RepResult] = []
    for case_id in selected_ids:
        if case_id not in cases:
            raise KeyError(f"Unknown case id {case_id!r}; have {sorted(cases)}")
        case = cases[case_id]
        trace_path = resolve_trace_path(
            case_id, agent=profile, data_suite=tag, traces_root=traces_root
        )
        for stage in selected_stages:
            eval_fn = _STAGE_EVAL[stage]
            for rep in range(n_reps):
                checks, _ = eval_fn(
                    agent=profile,
                    case=case,
                    trace_path=trace_path,
                    run_judges=run_judges,
                )
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

    first_keys = {(r.test_case_id, r.stage) for r in reps}
    single_ok = True
    for case_id, stage in first_keys:
        first = next(
            r
            for r in reps
            if r.test_case_id == case_id and r.stage == stage and r.rep == 0
        )
        if not first.passed:
            single_ok = False
            break

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
