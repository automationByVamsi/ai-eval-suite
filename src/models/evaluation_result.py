"""
Two result shapes:

- EvaluationResult: output of `src.main` running one TestCase end-to-end
  through an agent + its metrics.
- StageEvaluationResult: output of a BaseStageEvaluator running one captured
  trace through Layer 1 (deterministic) + Layer 2 (judge metric) checks.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

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


class StageEvaluationResult(BaseModel):
    stage_name: str
    test_case_id: str
    agent_name: str = ""
    question: str = ""
    answer: str = ""
    context: list[str] = Field(default_factory=list)
    latency_ms: Optional[float] = None
    deterministic_results: list[DeterministicCheckResult] = Field(default_factory=list)
    metric_results: list[MetricResult] = Field(default_factory=list)
    result_fields: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        det_ok = all(r.passed for r in self.deterministic_results)
        metrics_ok = all(r.passed for r in self.metric_results)
        return det_ok and metrics_ok

    @property
    def failed_reasons(self) -> list[str]:
        reasons = [r.reason for r in self.deterministic_results if not r.passed]
        reasons += [f"{m.name}: {m.reason}" for m in self.metric_results if not m.passed]
        return reasons

    def print_summary(self) -> None:
        status = "PASS" if self.passed else "FAIL"
        print(f"[{status}] {self.stage_name} :: {self.test_case_id}")
        for field, value in self.result_fields.items():
            print(f"  - {field}: {value}")
        for det in self.deterministic_results:
            mark = "ok" if det.passed else "FAIL"
            print(f"  - [{mark}] (deterministic) {det.name}: {det.reason}")
        for m in self.metric_results:
            mark = "ok" if m.passed else "FAIL"
            print(f"  - [{mark}] (judge) {m.name}: score={m.score:.2f} (threshold={m.threshold}) {m.reason}")
