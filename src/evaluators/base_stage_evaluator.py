"""
Template-method flow every stage evaluator follows:

  1. load raw trace (JSON off disk)
  2. parse_trace()            <- subclass hook
  3. build TestCase + AgentResponse (generic, from the parsed object)
  4. run_deterministic()      <- subclass hook (Layer 1)
  5. StageMetricRunner.run()  (Layer 2, YAML-driven judge metrics)
  6. return a StageEvaluationResult

Subclasses only fill in the four hooks below - the flow itself never
changes, so adding a new stage never touches this file.
"""

from abc import ABC, abstractmethod
from typing import Any

from src.evaluators.stage_metric_runner import StageMetricRunner
from src.models.agent_response import AgentResponse
from src.models.evaluation_result import DeterministicCheckResult, StageEvaluationResult
from src.models.test_case import TestCase
from src.parsers.trace_parser import load_raw_trace
from src.runners.factories import MetricFactory


class BaseStageEvaluator(ABC):
    stage_name: str
    agent_profile: str

    def __init__(self, metric_factory: MetricFactory, stage_config: dict):
        self.metric_runner = StageMetricRunner(metric_factory, self.agent_profile, stage_config)

    def evaluate(self, trace_path: str) -> StageEvaluationResult:
        raw = load_raw_trace(trace_path)
        parsed = self.parse_trace(raw)
        test_case = TestCase.model_validate(raw["test_case"])

        response = AgentResponse(
            answer=parsed.answer,
            raw_output=raw.get("raw_output"),
            context=parsed.context,
            events=parsed.events,
            metadata=self.get_response_metadata(parsed),
            session_id=parsed.session_id,
            latency_ms=parsed.latency_ms,
        )

        deterministic_results = self.run_deterministic(parsed)
        metric_results = self.metric_runner.run(test_case, response)

        return StageEvaluationResult(
            stage_name=self.stage_name,
            test_case_id=test_case.test_case_id,
            agent_name=test_case.agent_name,
            question=test_case.input.get("question", ""),
            answer=response.answer,
            context=response.context,
            latency_ms=response.latency_ms,
            deterministic_results=deterministic_results,
            metric_results=metric_results,
            result_fields=self.get_result_fields(parsed),
        )

    @abstractmethod
    def parse_trace(self, raw: dict[str, Any]) -> Any:
        """Raw trace dict -> a typed, stage-specific object (see parsers/<agent>/models.py)."""

    @abstractmethod
    def run_deterministic(self, parsed: Any) -> list[DeterministicCheckResult]:
        """Layer 1: fast, cheap, code-based assertions on the parsed trace."""

    @abstractmethod
    def get_response_metadata(self, parsed: Any) -> dict[str, Any]:
        """Data judge metrics can reference via a metric's `*_source` config, e.g. {'rewritten_query': ...}."""

    @abstractmethod
    def get_result_fields(self, parsed: Any) -> dict[str, Any]:
        """Values shown in the report / print_summary()."""
