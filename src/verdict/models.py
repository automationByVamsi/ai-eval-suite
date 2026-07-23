"""Lightweight result shapes for multi-run reliability scoring."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CheckObservation(BaseModel):
    """One check/metric on one repetition."""

    name: str
    kind: str  # "deterministic" | "judge"
    passed: bool
    score: Optional[float] = None
    threshold: Optional[float] = None
    reason: str = ""


class RepResult(BaseModel):
    """One (case × stage × repetition) evaluation."""

    test_case_id: str
    stage: str
    rep: int
    passed: bool
    checks: list[CheckObservation] = Field(default_factory=list)
    simulated: bool = False


class MetricAggregate(BaseModel):
    """Distribution for one (case × stage × check) across reps."""

    test_case_id: str
    stage: str
    name: str
    kind: str
    n: int
    pass_rate: float
    mean_score: Optional[float] = None
    std_score: Optional[float] = None
    scores: list[float] = Field(default_factory=list)

    @property
    def single_run_label(self) -> str:
        """What today's board would show if it only saw one sample."""
        if self.pass_rate >= 1.0:
            return "PASS"
        if self.pass_rate <= 0.0:
            return "FAIL"
        return "FLAKY"


class DiffRow(BaseModel):
    test_case_id: str
    stage: str
    name: str
    kind: str
    baseline_pass_rate: float
    current_pass_rate: float
    delta: float
    status: str  # "ok" | "regression" | "improved" | "new"


class VerdictReport(BaseModel):
    profile: str
    tag: str
    n_reps: int
    run_judges: bool
    simulate_regression: bool = False
    aggregates: list[MetricAggregate] = Field(default_factory=list)
    diffs: list[DiffRow] = Field(default_factory=list)
    single_run_all_passed: bool = True
    has_regression: bool = False
