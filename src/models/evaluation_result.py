"""
Evaluation result shapes.

- EvaluationResult: end-to-end agent + metrics run (src.main)
- CaseEvaluationResult: one stage/suite × one case (stage-wise dashboard)
- E2ECaseResult: one case with nested stage results (e2e dashboard)
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from src.models.metric_result import MetricResult


class DeterministicCheckResult(BaseModel):
    name: str
    passed: bool
    reason: str = ""


class EvaluationResult(BaseModel):
    test_case_id: str
    agent_name: str
    passed: bool
    metric_results: list[MetricResult] = Field(default_factory=list)
    error: Optional[str] = None

    @property
    def failed_reasons(self) -> list[str]:
        if self.error:
            return [self.error]
        return [f"{m.name}: {m.reason}" for m in self.metric_results if not m.passed]

    def print_summary(self) -> None:
        status = "PASS" if self.passed else "FAIL"
        print(f"[{status}] {self.test_case_id} ({self.agent_name})")
        for m in self.metric_results:
            mark = "ok" if m.passed else "FAIL"
            print(f"  - [{mark}] {m.name}: score={m.score:.2f} (threshold={m.threshold}) {m.reason}")
        if self.error:
            print(f"  - [ERROR] {self.error}")


class CaseEvaluationResult(BaseModel):
    """One stage/suite × one case for the stage-wise dashboard."""

    eval_name: str
    test_case_id: str
    agent_name: str = ""
    question: str = ""
    answer: str = ""
    # Ground truth for judges / dashboard: FF = aggregate chunks; KA may leave empty.
    context: list[str] = Field(default_factory=list)
    # SME / case golden text (e.g. KA expected_answer).
    expected_output: str = ""
    latency_ms: Optional[float] = None
    deterministic_results: list[DeterministicCheckResult] = Field(default_factory=list)
    metric_results: list[MetricResult] = Field(default_factory=list)
    result_fields: dict[str, Any] = Field(default_factory=dict)
    # Set by the dashboard when aggregating across runs (not required at publish time).
    run_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_stage_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "eval_name" not in data and "stage_name" in data:
            data = {**data, "eval_name": data["stage_name"]}
        return data

    @property
    def deterministic_passed(self) -> bool:
        return all(r.passed for r in self.deterministic_results)

    @property
    def passed(self) -> bool:
        det_ok = self.deterministic_passed
        metrics_ok = all(r.passed for r in self.metric_results)
        return det_ok and metrics_ok

    @property
    def failed_reasons(self) -> list[str]:
        reasons = [r.reason for r in self.deterministic_results if not r.passed]
        reasons += [f"{m.name}: {m.reason}" for m in self.metric_results if not m.passed]
        return reasons

    def print_summary(self) -> None:
        status = "PASS" if self.passed else "FAIL"
        print(f"[{status}] {self.eval_name} :: {self.test_case_id}")
        for field, value in self.result_fields.items():
            print(f"  - {field}: {value}")
        for det in self.deterministic_results:
            mark = "ok" if det.passed else "FAIL"
            print(f"  - [{mark}] (deterministic) {det.name}: {det.reason}")
        for m in self.metric_results:
            mark = "ok" if m.passed else "FAIL"
            print(f"  - [{mark}] (judge) {m.name}: score={m.score:.2f} (threshold={m.threshold}) {m.reason}")


class E2ECaseResult(BaseModel):
    """
    One test case with nested stage results (e2e dashboard).
    kind=e2e so the dashboard can distinguish from stage-level files.
    """

    kind: str = "e2e"
    test_case_id: str
    agent_name: str = ""
    question: str = ""
    latency_ms: Optional[float] = None
    stages: list[CaseEvaluationResult] = Field(default_factory=list)
    # Set by the dashboard when aggregating across runs (not required at publish time).
    run_id: str = ""

    @property
    def deterministic_passed(self) -> bool:
        return bool(self.stages) and all(s.deterministic_passed for s in self.stages)

    @property
    def passed(self) -> bool:
        """E2E hard gate = all stages' deterministic checks (matches pytest default)."""
        return self.deterministic_passed

    def print_summary(self) -> None:
        status = "PASS" if self.passed else "FAIL"
        print(f"[{status}] e2e :: {self.test_case_id} ({len(self.stages)} stages)")
        for s in self.stages:
            det_ok = sum(c.passed for c in s.deterministic_results)
            det_n = len(s.deterministic_results)
            mark = "ok" if s.deterministic_passed else "FAIL"
            print(f"  - [{mark}] {s.eval_name}: deterministic {det_ok}/{det_n}")


# Alias for older imports
StageEvaluationResult = CaseEvaluationResult
