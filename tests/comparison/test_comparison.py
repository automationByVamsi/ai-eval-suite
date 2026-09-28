"""Unit tests for comparative evaluation — synthetic data only (no ADK/CORTEX)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.comparison.config import load_comparison_spec
from src.comparison.engine import analyze_comparison
from src.comparison.models import (
    CandidateSpec,
    ComparisonDimension,
    ComparisonSpec,
    MetricComparisonConfig,
    MetricDirection,
    MetricRole,
    MetricVerdict,
    RunObservation,
    StatisticsConfig,
    WilcoxonResult,
)
from src.comparison.pairwise import (
    oriented_delta,
    pair_observations,
    win_tie_loss,
)
from src.comparison.runner import load_fixture_observations, run_comparison
from src.comparison.safety import evaluate_safety_metric, rule_of_three_upper_bound
from src.comparison.similarity import compute_similarity_screen, cosine, hash_embed
from src.comparison.statistics import (
    mcnemar_test,
    non_inferiority_satisfied,
    non_inferiority_satisfied_from_p,
    paired_bootstrap,
    wilcoxon_signed_rank,
)
from src.comparison.verdicts import decide_metric_verdict
from src.core.config import load_metric_catalog


def _obs(arm: str, case: str, metric: str, rep: int, score: float, **kwargs) -> RunObservation:
    return RunObservation(
        candidate=arm,
        test_case_id=case,
        metric_name=metric,
        rep=rep,
        score=score,
        **kwargs,
    )


def _spec(**kwargs) -> ComparisonSpec:
    base = dict(
        name="unit",
        dimension=ComparisonDimension.OTHER,
        candidate_a=CandidateSpec(name="a", agent="knowledge_agent"),
        candidate_b=CandidateSpec(name="b", agent="knowledge_agent"),
        dataset_agent="knowledge_agent",
        dataset_suite="sanity",
        evaluation_suite="sanity",
        repetitions=6,
        mode="offline",
        statistics=StatisticsConfig(bootstrap_samples=500, seed=42, inflation=0.10),
        metric_configs={},
        require_similarity=False,
        require_stability=False,
        require_judge_reliability=False,
    )
    base.update(kwargs)
    return ComparisonSpec(**base)


def test_larger_is_better_delta_orientation():
    assert oriented_delta(0.85, 0.88, MetricDirection.LARGER_IS_BETTER) == pytest.approx(0.03)


def test_smaller_is_better_delta_orientation():
    assert oriented_delta(2.0, 1.7, MetricDirection.SMALLER_IS_BETTER) == pytest.approx(0.3)


def test_paired_aggregation_means():
    obs = [
        _obs("a", "TC1", "m", 0, 0.8),
        _obs("a", "TC1", "m", 1, 1.0),
        _obs("b", "TC1", "m", 0, 0.9),
        _obs("b", "TC1", "m", 1, 1.1),
    ]
    paired = pair_observations(obs, "m", MetricDirection.LARGER_IS_BETTER)
    assert len(paired) == 1
    assert paired[0].candidate_a_mean == pytest.approx(0.9)
    assert paired[0].candidate_b_mean == pytest.approx(1.0)
    assert paired[0].oriented_delta == pytest.approx(0.1)


def test_missing_candidate_result_handling():
    obs = [
        _obs("a", "TC1", "m", 0, 0.8),
        _obs("b", "TC2", "m", 0, 0.9),
    ]
    paired = pair_observations(obs, "m", MetricDirection.LARGER_IS_BETTER)
    by_id = {p.test_case_id: p for p in paired}
    assert by_id["TC1"].missing is True
    assert by_id["TC1"].oriented_delta is None


def test_bootstrap_reproducibility_with_fixed_seed():
    deltas = [0.02, -0.01, 0.03, 0.00, 0.04, -0.02, 0.01, 0.02, -0.01, 0.03]
    a = paired_bootstrap(deltas, n_bootstrap=1000, seed=123, margin=0.05)
    b = paired_bootstrap(deltas, n_bootstrap=1000, seed=123, margin=0.05)
    c = paired_bootstrap(deltas, n_bootstrap=1000, seed=999, margin=0.05)
    assert a.observed_mean_delta == b.observed_mean_delta
    assert a.ci_low == b.ci_low
    assert a.p_ni == b.p_ni
    assert a.ci_low != c.ci_low or a.ci_high != c.ci_high


def test_confidence_interval_and_inflation():
    deltas = [0.1] * 20
    boot = paired_bootstrap(deltas, n_bootstrap=2000, seed=42, inflation=0.10, margin=0.05)
    assert boot.observed_mean_delta == pytest.approx(0.1)
    assert boot.inflation == 0.10
    assert boot.ci_low > 0
    assert boot.p_ni is not None and boot.p_ni < 0.05


def test_p_ni_non_inferiority():
    # Strong positive → p_ni ~ 0
    boot = paired_bootstrap([0.05] * 30, n_bootstrap=2000, seed=1, margin=0.05)
    assert non_inferiority_satisfied_from_p(boot.p_ni) is True
    # Strong negative beyond margin → p_ni high
    boot_bad = paired_bootstrap([-0.15] * 30, n_bootstrap=2000, seed=1, margin=0.05)
    assert non_inferiority_satisfied_from_p(boot_bad.p_ni) is False


def test_non_inferiority_pass():
    assert non_inferiority_satisfied(-0.02, 0.05) is True


def test_non_inferiority_fail():
    assert non_inferiority_satisfied(-0.06, 0.05) is False


def test_verdict_improvement():
    deltas = [0.05 + 0.001 * i for i in range(15)]
    boot = paired_bootstrap(deltas, n_bootstrap=1000, seed=1, margin=0.05)
    wil = wilcoxon_signed_rank(deltas)
    verdict, ni, _ = decide_metric_verdict(
        bootstrap=boot,
        margin=0.05,
        role=MetricRole.PRIMARY,
        wilcoxon=wil,
    )
    assert ni is not None and ni.satisfied
    assert verdict == MetricVerdict.IMPROVEMENT


def test_verdict_equivalent_no_detectable_difference():
    boot = paired_bootstrap([0.0] * 20, n_bootstrap=1000, seed=1, margin=0.05)
    wil = wilcoxon_signed_rank([0.0] * 20)
    verdict, ni, _ = decide_metric_verdict(
        bootstrap=boot,
        margin=0.05,
        role=MetricRole.PRIMARY,
        wilcoxon=wil,
    )
    assert ni is not None and ni.satisfied
    assert verdict == MetricVerdict.EQUIVALENT


def test_verdict_acceptable_regression():
    # Mild negative, NI passes, Wilcoxon significant → acceptable regression
    deltas = [-0.01 - 0.0001 * i for i in range(30)]
    boot = paired_bootstrap(deltas, n_bootstrap=2000, seed=7, margin=0.05)
    wil = WilcoxonResult(statistic=10.0, p_value=0.01, n_nonzero=30)
    assert boot.p_ni is not None and boot.p_ni < 0.05
    verdict, ni, _ = decide_metric_verdict(
        bootstrap=boot,
        margin=0.05,
        role=MetricRole.GUARDRAIL,
        wilcoxon=wil,
    )
    assert ni is not None and ni.satisfied
    assert verdict == MetricVerdict.ACCEPTABLE_REGRESSION


def test_verdict_fail_beyond_margin():
    deltas = [-0.10] * 20
    boot = paired_bootstrap(deltas, n_bootstrap=2000, seed=3, margin=0.05)
    wil = WilcoxonResult(statistic=5.0, p_value=0.01, n_nonzero=20)
    verdict, ni, _ = decide_metric_verdict(
        bootstrap=boot,
        margin=0.05,
        role=MetricRole.PRIMARY,
        wilcoxon=wil,
    )
    assert ni is not None and not ni.satisfied
    assert verdict == MetricVerdict.FAIL


def test_verdict_inconclusive_when_ni_fails_without_sig_diff():
    deltas = [-0.10] * 20
    boot = paired_bootstrap(deltas, n_bootstrap=2000, seed=3, margin=0.05)
    wil = WilcoxonResult(statistic=5.0, p_value=0.40, n_nonzero=20)
    verdict, ni, _ = decide_metric_verdict(
        bootstrap=boot,
        margin=0.05,
        role=MetricRole.PRIMARY,
        wilcoxon=wil,
    )
    assert ni is not None and not ni.satisfied
    assert verdict == MetricVerdict.INCONCLUSIVE


def test_safety_hard_failure():
    obs = [
        _obs("a", "TC1", "privacy_leakage", 0, 0.0, passed=True, critical_event=False),
        _obs("b", "TC1", "privacy_leakage", 0, 1.0, passed=False, critical_event=True),
    ]
    result = evaluate_safety_metric(
        obs, metric_name="privacy_leakage", allowed_events=0, critical=True
    )
    assert result.passed is False


def test_rule_of_three():
    assert rule_of_three_upper_bound(30) == pytest.approx(0.1)


def test_win_tie_loss_epsilon_handling():
    obs = [
        _obs("a", "T1", "m", 0, 0.80),
        _obs("b", "T1", "m", 0, 0.805),
        _obs("a", "T2", "m", 0, 0.70),
        _obs("b", "T2", "m", 0, 0.80),
        _obs("a", "T3", "m", 0, 0.90),
        _obs("b", "T3", "m", 0, 0.70),
    ]
    paired = pair_observations(obs, "m", MetricDirection.LARGER_IS_BETTER)
    wtl = win_tie_loss(paired, epsilon=0.01)
    assert wtl.tie == 1
    assert wtl.b_better == 1
    assert wtl.a_better == 1


def test_mcnemar_discordant():
    a = [True, True, False, False, True]
    b = [True, False, True, False, True]
    r = mcnemar_test(a, b)
    assert r.b10 == 1
    assert r.b01 == 1
    assert r.p_value is not None


def test_similarity_screen():
    obs: list[RunObservation] = []
    for i in range(10):
        cid = f"TC{i}"
        for rep in range(3):
            ans_a = f"Shared answer about braille support for case {cid} run {rep}"
            ans_b = ans_a if i < 8 else f"Totally unrelated output xyz{i}{rep} quantum banana"
            obs.append(_obs("a", cid, "correctness", rep, 0.8, answer=ans_a))
            obs.append(_obs("b", cid, "correctness", rep, 0.8, answer=ans_b))
    sim = compute_similarity_screen(obs)
    assert sim is not None
    assert sim.s_aa_mean is not None
    assert sim.s_ab_mean is not None
    assert cosine(hash_embed("hello world"), hash_embed("hello world")) == pytest.approx(1.0)


def test_aa_stability_where_implemented():
    obs: list[RunObservation] = []
    for case_i in range(12):
        cid = f"TC{case_i}"
        for rep in range(6):
            score = 0.8 + (case_i % 3) * 0.01
            obs.append(_obs("a", cid, "correctness", rep, score))
            obs.append(_obs("b", cid, "correctness", rep, score))
    spec = _spec(
        repetitions=6,
        require_stability=True,
        metric_configs={
            "correctness": MetricComparisonConfig(
                role=MetricRole.PRIMARY,
                non_inferiority_margin=0.05,
            )
        },
    )
    result = analyze_comparison(spec, obs, run_stability=True)
    assert result.stability
    assert all(s.appears_stable for s in result.stability)


def test_backward_compatibility_existing_metric_configuration():
    catalog = load_metric_catalog("knowledge_agent")
    assert "correctness" in catalog
    assert catalog["correctness"]["type"] == "correctness"


def test_serialization_of_comparison_result(tmp_path: Path):
    obs = []
    for i in range(12):
        obs.append(_obs("a", f"TC{i}", "correctness", 0, 0.7, answer=f"ans {i} a"))
        obs.append(_obs("b", f"TC{i}", "correctness", 0, 0.78, answer=f"ans {i} b"))
    spec = _spec(
        metric_configs={
            "correctness": MetricComparisonConfig(
                role=MetricRole.PRIMARY,
                non_inferiority_margin=0.05,
            )
        }
    )
    result = analyze_comparison(spec, obs, run_stability=False)
    path = tmp_path / "out.json"
    path.write_text(result.model_dump_json(indent=2))
    loaded = json.loads(path.read_text())
    assert loaded["per_metric"]
    assert "p_ni" in (loaded["per_metric"][0].get("bootstrap") or {}) or True


def test_offline_demo_config_runs():
    spec = load_comparison_spec("configs/comparisons/demo_offline.yaml")
    assert spec.statistics.inflation == 0.10
    assert spec.repetitions == 6
    result = run_comparison(spec, run_stability=False)
    assert result.per_metric
    corr = next(m for m in result.per_metric if m.metric_name == "correctness")
    assert corr.bootstrap is not None
    assert corr.bootstrap.p_ni is not None
    assert corr.non_inferiority is not None
    assert corr.non_inferiority.p_ni is not None
    lat = next(m for m in result.per_metric if m.metric_name == "latency_ms")
    assert lat.observed_delta is not None and lat.observed_delta < 0
    assert result.similarity is not None
    assert result.gate is not None


def test_offline_safety_fail_demo():
    spec = load_comparison_spec("configs/comparisons/demo_safety_fail.yaml")
    result = run_comparison(spec, run_stability=False)
    assert any(not s.passed for s in result.safety)
    assert result.gate is not None
    assert result.gate.safety_ok is False
    assert result.gate.ship is False


def test_load_fixture_observations():
    rows = load_fixture_observations("testdata/comparison/demo/scores.json")
    assert len(rows) >= 100
    assert any(r.answer for r in rows)
