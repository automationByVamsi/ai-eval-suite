"""
VERDICT — live multi-run reliability + baseline regression for any agent.

Each repetition invokes ADK (run_case), then scores the fresh response.
Traces are still saved under outputs/traces/ as a side effect.

  python -m scripts.run_verdict --agent knowledge_agent --n 5
  python -m scripts.run_verdict --agent fact_find_workflow --n 5
"""

from __future__ import annotations

from pathlib import Path

from src.runners.case_runner import load_cases, run_case
from src.verdict.aggregate import aggregate_reps
from src.verdict.baseline import load_baseline, save_baseline
from src.verdict.diff import diff_against_baseline
from src.verdict.models import CheckObservation, RepResult, VerdictReport
from src.verdict.registry import get_pack, load_builtin_packs
from src.verdict.report import print_report


def _inject_regression(
    checks: list[CheckObservation],
    *,
    fail_names: frozenset[str],
    rep: int,
    n_reps: int,
) -> list[CheckObservation]:
    """Fail selected checks on most reps (lucky first rep can still look green)."""
    if not fail_names:
        fail_names = frozenset({checks[0].name}) if checks else frozenset()
    if not fail_names:
        return checks
    if rep < max(1, n_reps // 5):
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
                            or "VERDICT simulate-regression: intentional upstream drop"
                        ),
                    }
                )
            )
        else:
            out.append(c)
    return out


def run_verdict(
    *,
    agent: str = "knowledge_agent",
    suite: str | None = None,
    n_reps: int = 5,
    case_ids: list[str] | None = None,
    packs: list[str] | None = None,
    run_judges: bool = False,
    simulate_regression: bool = False,
    save_as_baseline: bool = False,
    compare_baseline: bool = True,
    baseline_name: str = "latest",
    drop_threshold: float = 0.15,
    output_dir: str = "outputs/verdict",
    traces_root: str = "outputs/traces",
    # Back-compat aliases
    profile: str | None = None,
    tag: str | None = None,
    stages: list[str] | None = None,
) -> VerdictReport:
    """Live-invoke each case N times; aggregate; optionally diff a baseline."""
    load_builtin_packs()

    agent = profile or agent
    pack = get_pack(agent)
    suite = tag or suite or pack.default_suite
    selected_packs = packs or stages or list(pack.packs.keys())

    unknown = [p for p in selected_packs if p not in pack.packs]
    if unknown:
        raise KeyError(
            f"Unknown pack(s) {unknown} for {agent}; have {sorted(pack.packs)}"
        )

    cases_list = load_cases(agent, suite)
    cases = {str(c["test_case_id"]): c for c in cases_list}
    selected_ids = case_ids or sorted(cases.keys())

    reps: list[RepResult] = []
    for case_id in selected_ids:
        if case_id not in cases:
            raise KeyError(f"Unknown case id {case_id!r}; have {sorted(cases)}")
        case = cases[case_id]
        for pack_name in selected_packs:
            eval_fn = pack.packs[pack_name]
            for rep in range(n_reps):
                print(f"[verdict] live {agent}/{case_id} pack={pack_name} rep={rep + 1}/{n_reps}")
                live = run_case(agent, case, suite, output_dir=traces_root)
                checks = eval_fn(agent, case, live.response, run_judges)
                if simulate_regression:
                    checks = _inject_regression(
                        checks,
                        fail_names=pack.sim_fail.get(pack_name, frozenset()),
                        rep=rep,
                        n_reps=n_reps,
                    )
                reps.append(
                    RepResult(
                        test_case_id=case_id,
                        stage=pack_name,
                        rep=rep,
                        passed=all(c.passed for c in checks),
                        checks=checks,
                        simulated=simulate_regression,
                    )
                )

    aggregates = aggregate_reps(reps)

    single_ok = True
    for case_id, pack_name in {(r.test_case_id, r.stage) for r in reps}:
        first = next(
            r
            for r in reps
            if r.test_case_id == case_id and r.stage == pack_name and r.rep == 0
        )
        if not first.passed:
            single_ok = False
            break

    diffs = []
    has_regression = False
    baseline_root = Path(output_dir) / "baselines"
    if compare_baseline:
        try:
            baseline = load_baseline(root=baseline_root, profile=agent, name=baseline_name)
            diffs = diff_against_baseline(aggregates, baseline, drop_threshold=drop_threshold)
            has_regression = any(d.status == "regression" for d in diffs)
        except FileNotFoundError:
            diffs = []

    if save_as_baseline:
        save_baseline(
            aggregates,
            root=baseline_root,
            profile=agent,
            name=baseline_name,
            meta={
                "n_reps": n_reps,
                "run_judges": run_judges,
                "simulate_regression": simulate_regression,
                "suite": suite,
                "mode": "live",
            },
        )

    run_dir = Path(output_dir) / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    report = VerdictReport(
        profile=agent,
        tag=suite,
        n_reps=n_reps,
        run_judges=run_judges,
        simulate_regression=simulate_regression,
        aggregates=aggregates,
        diffs=diffs,
        single_run_all_passed=single_ok,
        has_regression=has_regression,
    )
    stamp = "simulated" if simulate_regression else "current"
    (run_dir / f"{agent}_{stamp}.json").write_text(report.model_dump_json(indent=2))

    print_report(report)
    return report
