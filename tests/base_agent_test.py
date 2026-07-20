"""
BaseAgentTest — agent-agnostic test helpers.

Owns only what every agent needs:
  - load test cases
  - capture / reuse traces
  - load a captured trace
  - publish results to the dashboard

Agent-specific parsing and stage/suite judge wiring belong in
tests/<agent>/base.py (e.g. KnowledgeAgentTest).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.models.evaluation_result import (
    CaseEvaluationResult,
    DeterministicCheckResult,
    E2ECaseResult,
)
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.parsers.trace_parser import load_raw_trace
from src.reporting.persist import ensure_run_dir, save_e2e_result, save_eval_result
from src.runners.factories import AgentFactory
from src.runners.trace_capture import ensure_traces


class BaseAgentTest:
    """Shared setup / capture / publish. Subclass must set profile (+ tag in the test)."""

    agents_config: str = "configs/agents.yaml"
    cortex_config: str = "configs/cortex.yaml"
    dashboard_dir: str = "outputs/dashboard"

    profile: str = ""
    tag: str = ""

    def _run_dir(self) -> str:
        """Timestamped run folder under dashboard_dir (one per pytest process)."""
        return str(ensure_run_dir(self.dashboard_dir))

    def load_cases(self) -> dict[str, TestCase]:
        test_dir = Path("testdata") / self.profile / self.tag
        files = sorted(test_dir.glob("*.json"))
        assert files, f"No test cases under {test_dir}"
        cases = [TestCase.from_json_file(str(f)) for f in files]
        return {c.test_case_id: c for c in cases}

    def ensure_traces(self, cases: list[TestCase]) -> None:
        mode = os.environ.get("DEMO_MODE", "cache")
        trace_dir = Path("outputs/traces") / self.profile / self.tag
        factory = AgentFactory(self.agents_config)
        ensure_traces(cases, trace_dir, mode, factory)

    def load_trace(self, test_case_id: str) -> dict[str, Any]:
        path = Path("outputs/traces") / self.profile / self.tag / f"{test_case_id}.json"
        return load_raw_trace(path)

    def publish(
        self,
        *,
        eval_name: str,
        test_case: TestCase,
        question: str = "",
        answer: str = "",
        context: list[str] | None = None,
        latency_ms: float | None = None,
        deterministic_results: list[DeterministicCheckResult] | None = None,
        metric_results: list[MetricResult] | None = None,
        result_fields: dict[str, Any] | None = None,
    ) -> CaseEvaluationResult:
        """Write one case result JSON for the Streamlit dashboard; return the result."""
        result = CaseEvaluationResult(
            eval_name=eval_name,
            test_case_id=test_case.test_case_id,
            agent_name=test_case.agent_name,
            question=question,
            answer=answer,
            context=context or [],
            latency_ms=latency_ms,
            deterministic_results=deterministic_results or [],
            metric_results=metric_results or [],
            result_fields=result_fields or {},
        )
        result.print_summary()
        save_eval_result(result, self._run_dir())
        return result

    def publish_e2e(
        self,
        *,
        test_case: TestCase,
        stages: list[CaseEvaluationResult],
        question: str = "",
        latency_ms: float | None = None,
    ) -> Path:
        """Write one e2e case rollup JSON (nested stages) for the dashboard."""
        result = E2ECaseResult(
            test_case_id=test_case.test_case_id,
            agent_name=test_case.agent_name,
            question=question or (stages[0].question if stages else ""),
            latency_ms=latency_ms,
            stages=stages,
        )
        result.print_summary()
        return save_e2e_result(result, self._run_dir())
