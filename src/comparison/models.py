"""
Typed shapes for A/B comparative evaluation.

Candidate A / Candidate B are intentional experiment arms — not hard-coded
to "model". Pairing is preserved per (test_case_id, metric_name).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MetricDirection(str, Enum):
    """How to orient deltas so positive always means B is better."""

    LARGER_IS_BETTER = "larger_is_better"
    SMALLER_IS_BETTER = "smaller_is_better"


class MetricRole(str, Enum):
    """How a metric participates in the release gate."""

    PRIMARY = "primary"
    GUARDRAIL = "guardrail"
    SAFETY = "safety"
    DIAGNOSTIC = "diagnostic"


class MetricVerdict(str, Enum):
    """Per-metric comparative conclusion (not a global winner)."""

    IMPROVEMENT = "IMPROVEMENT"
    EQUIVALENT = "EQUIVALENT"
    ACCEPTABLE_REGRESSION = "ACCEPTABLE_REGRESSION"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"


class ComparisonDimension(str, Enum):
    """Declared single dimension under comparison."""

    MODEL = "model"
    PROMPT = "prompt"
    TOOLS = "tools"
    RETRIEVAL = "retrieval"
    CONFIG = "config"
    DEPLOYMENT = "deployment"
    RELEASE = "release"
    OTHER = "other"


class CandidateSpec(BaseModel):
    """One experiment arm."""

    name: str
    agent: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricComparisonConfig(BaseModel):
    """Optional per-metric comparison metadata (from catalog or experiment)."""

    role: MetricRole = MetricRole.DIAGNOSTIC
    direction: MetricDirection = MetricDirection.LARGER_IS_BETTER
    non_inferiority_margin: Optional[float] = None
    critical: bool = False
    allowed_events: int = 0
    tie_epsilon: Optional[float] = None
    binary: bool = False  # use McNemar on pass/fail instead of score bootstrap


class StatisticsConfig(BaseModel):
    """Paired bootstrap / diagnostic settings (Hive methodology defaults)."""

    bootstrap_samples: int = 10_000
    confidence_level: float = 0.95
    alpha: float = 0.05
    seed: int = 42
    tie_epsilon: float = 0.01
    inflation: float = 0.10  # conservatism allowance for case heterogeneity
    similarity_consistency_tolerance: float = 0.05
    degraded_share_limit: Optional[float] = None  # optional heterogeneity flag


class ComparisonSpec(BaseModel):
    """Experiment definition loaded from configs/comparisons/*.yaml."""

    name: str
    description: str = ""
    dimension: ComparisonDimension = ComparisonDimension.OTHER
    candidate_a: CandidateSpec
    candidate_b: CandidateSpec
    dataset_agent: str
    dataset_suite: str
    evaluation_suite: str
    repetitions: int = 6  # six-run design (noise floor)
    statistics: StatisticsConfig = Field(default_factory=StatisticsConfig)
    metric_configs: dict[str, MetricComparisonConfig] = Field(default_factory=dict)
    mode: str = "offline"
    fixtures_path: Optional[str] = None
    output_dir: str = "outputs/comparison"
    warnings: list[str] = Field(default_factory=list)
    # Ops budgets (optional) — leadership decision if exceeded
    latency_p95_budget_ms: Optional[float] = None
    cost_budget_per_task: Optional[float] = None
    require_similarity: bool = True
    require_stability: bool = True
    require_judge_reliability: bool = True
    divergences_reviewed: bool = False


class RunObservation(BaseModel):
    """One (candidate × test_case × metric × repetition) score."""

    candidate: str  # "a" | "b"
    test_case_id: str
    metric_name: str
    rep: int
    score: Optional[float] = None
    passed: Optional[bool] = None
    latency_ms: Optional[float] = None
    cost: Optional[float] = None
    reason: str = ""
    critical_event: bool = False
    answer: Optional[str] = None
    embedding: Optional[list[float]] = None
    judge_rescores: Optional[list[float]] = None


class PairedObservation(BaseModel):
    """Paired per-test-case means for one metric (after averaging reps)."""

    test_case_id: str
    metric_name: str
    candidate_a_runs: list[float] = Field(default_factory=list)
    candidate_b_runs: list[float] = Field(default_factory=list)
    candidate_a_mean: Optional[float] = None
    candidate_b_mean: Optional[float] = None
    oriented_delta: Optional[float] = None
    missing: bool = False


class WinTieLoss(BaseModel):
    """Per-test-case descriptive counts (diagnostic only)."""

    b_better: int = 0
    tie: int = 0
    a_better: int = 0
    epsilon: float = 0.01


class CaseDelta(BaseModel):
    """One test case's A/B scores for top-regression / top-improvement lists."""

    test_case_id: str
    candidate_a_mean: float
    candidate_b_mean: float
    oriented_delta: float


class BootstrapResult(BaseModel):
    """Paired bootstrap summary for oriented deltas (inflated)."""

    observed_mean_delta: float
    ci_low: float
    ci_high: float
    one_sided_lower: float
    n_pairs: int
    n_bootstrap: int
    seed: int
    inflation: float = 0.10
    p_ni: Optional[float] = None


class WilcoxonResult(BaseModel):
    """Supporting difference test (p_diff)."""

    statistic: Optional[float] = None
    p_value: Optional[float] = None
    n_nonzero: int = 0
    note: str = ""


class McNemarResult(BaseModel):
    """Binary discordant-pair test."""

    b01: int = 0
    b10: int = 0
    n_discordant: int = 0
    p_value: Optional[float] = None
    note: str = ""


class NonInferiorityResult(BaseModel):
    """Non-inferiority gate: p_NI < alpha (H0: Δ ≤ −δ)."""

    margin: float
    one_sided_lower: float
    satisfied: bool
    p_ni: Optional[float] = None


class SafetyMetricResult(BaseModel):
    """Hard-gate view of a critical safety metric."""

    metric_name: str
    candidate_a_events: int
    candidate_b_events: int
    allowed_events: int
    critical: bool = True
    passed: bool
    rule_of_three_upper_bound: Optional[float] = None
    n_trials_b: int = 0
    note: str = ""


class StabilityResult(BaseModel):
    """A/A or B/B null-test summary including resolution vs tolerance."""

    arm: str  # "a" | "b"
    metric_name: str = ""
    observed_mean_delta: float
    ci_low: float
    ci_high: float
    n_pairs: int
    appears_stable: bool
    resolution: Optional[float] = None
    margin: Optional[float] = None
    tolerance_enforceable: Optional[bool] = None
    note: str = ""


class SimilarityResult(BaseModel):
    """Step 5 similarity screen (triage, not sole gate)."""

    s_aa_mean: Optional[float] = None
    s_aa_std: Optional[float] = None
    s_bb_mean: Optional[float] = None
    s_bb_std: Optional[float] = None
    s_ab_mean: Optional[float] = None
    s_ab_std: Optional[float] = None
    t_sim: Optional[float] = None
    divergent_case_ids: list[str] = Field(default_factory=list)
    inside_band: bool = True
    consistency_ok: bool = True
    consistency_note: str = ""
    n_cases: int = 0
    method: str = "hash_bow_answer"
    note: str = ""
    divergences_reviewed: bool = False  # set True in config/metadata if SME signed off


class JudgeVarianceResult(BaseModel):
    """σ_judge vs σ_gen for one metric."""

    metric_name: str
    role: MetricRole = MetricRole.DIAGNOSTIC
    sigma_judge: Optional[float] = None
    sigma_gen: Optional[float] = None
    reliable: bool = True
    demoted: bool = False
    note: str = ""


class MetricComparison(BaseModel):
    """Full comparative summary for one metric."""

    metric_name: str
    role: MetricRole
    direction: MetricDirection
    candidate_a_mean: Optional[float] = None
    candidate_b_mean: Optional[float] = None
    observed_delta: Optional[float] = None
    bootstrap: Optional[BootstrapResult] = None
    non_inferiority: Optional[NonInferiorityResult] = None
    wilcoxon: Optional[WilcoxonResult] = None
    mcnemar: Optional[McNemarResult] = None
    win_tie_loss: Optional[WinTieLoss] = None
    degraded_case_share: Optional[float] = None
    improved_case_share: Optional[float] = None
    top_regressions: list[CaseDelta] = Field(default_factory=list)
    top_improvements: list[CaseDelta] = Field(default_factory=list)
    paired: list[PairedObservation] = Field(default_factory=list)
    verdict: MetricVerdict = MetricVerdict.INCONCLUSIVE
    note: str = ""
    demoted_unreliable_judge: bool = False


class OperationalSummary(BaseModel):
    """Latency and cost — never fabricate cost."""

    candidate_a_latency_median_ms: Optional[float] = None
    candidate_a_latency_p95_ms: Optional[float] = None
    candidate_b_latency_median_ms: Optional[float] = None
    candidate_b_latency_p95_ms: Optional[float] = None
    candidate_a_cost_mean: Optional[float] = None
    candidate_b_cost_mean: Optional[float] = None
    cost_available: bool = False
    cost_note: str = "Cost unavailable — no token/pricing data in results."
    latency_within_budget: Optional[bool] = None
    cost_within_budget: Optional[bool] = None


class GateResult(BaseModel):
    """Step 8 decision rule — no weighted overall AI score."""

    comparison_acceptable: bool
    primary_ok: bool
    guardrails_ok: bool
    safety_ok: bool
    stability_ok: bool
    similarity_ok: bool = True
    consistency_ok: bool = True
    judge_reliability_ok: bool = True
    operations_ok: bool = True
    ship: bool = False
    conditions: dict[str, bool] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    """Machine-readable experiment output."""

    experiment_name: str
    description: str = ""
    dimension: ComparisonDimension
    candidate_a: CandidateSpec
    candidate_b: CandidateSpec
    dataset_agent: str
    dataset_suite: str
    evaluation_suite: str
    repetitions: int
    mode: str
    warnings: list[str] = Field(default_factory=list)
    per_metric: list[MetricComparison] = Field(default_factory=list)
    safety: list[SafetyMetricResult] = Field(default_factory=list)
    stability: list[StabilityResult] = Field(default_factory=list)
    similarity: Optional[SimilarityResult] = None
    judge_variance: list[JudgeVarianceResult] = Field(default_factory=list)
    operations: OperationalSummary = Field(default_factory=OperationalSummary)
    gate: Optional[GateResult] = None
