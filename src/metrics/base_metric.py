"""
BaseMetric is the contract every metric implements. DeepEvalMetric is the
shared base for anything scored by a DeepEval metric via the CORTEX judge -
it does the boring, repetitive part (mapping declarative `*_source` config
onto a DeepEval LLMTestCase) so each concrete metric only has to say which
DeepEval metric class to build.

Source mapping: a `<field>_source` config value is a name that gets resolved
against, in order: test_case.input, test_case.expected, response.metadata,
then a couple of well-known AgentResponse attributes (answer, context). This
is what lets configs/evaluations/.../*.yaml wire "input_source: question" or
"actual_source: rewritten_query" without any Python.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from deepeval.test_case import LLMTestCase, ToolCall

from src.clients.cortex_deepeval import CortexDeepEvalLLM
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase

_RESPONSE_ATTRS = {"answer", "context", "session_id", "latency_ms"}
# Aliases for common names that don't match an AgentResponse field 1:1.
_RESPONSE_ATTR_ALIASES = {"retrieval_context": "context"}


def resolve_field(source_name: Optional[str], test_case: TestCase, response: AgentResponse) -> Any:
    if not source_name:
        return None
    if source_name in test_case.input:
        return test_case.input[source_name]
    if source_name in test_case.expected:
        return test_case.expected[source_name]
    if source_name in response.metadata:
        return response.metadata[source_name]
    if source_name in _RESPONSE_ATTRS:
        return getattr(response, source_name)
    if source_name in _RESPONSE_ATTR_ALIASES:
        return getattr(response, _RESPONSE_ATTR_ALIASES[source_name])
    return None


def _as_tool_calls(value: Any) -> list[ToolCall] | None:
    if value is None:
        return None
    if isinstance(value, list) and (not value or isinstance(value[0], ToolCall)):
        return value
    if isinstance(value, list):
        out: list[ToolCall] = []
        for item in value:
            if isinstance(item, ToolCall):
                out.append(item)
            elif isinstance(item, str):
                out.append(ToolCall(name=item))
            elif isinstance(item, dict) and item.get("name"):
                out.append(
                    ToolCall(
                        name=str(item["name"]),
                        input_parameters=item.get("input_parameters") or item.get("args") or {},
                    )
                )
        return out
    return None


class BaseMetric(ABC):
    def __init__(self, name: str, threshold: float = 0.7, **_kwargs: Any):
        self.name = name
        self.threshold = threshold

    @abstractmethod
    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        raise NotImplementedError


class DeepEvalMetric(BaseMetric):
    """
    cortex_client is injected by MetricFactory - metrics are the only part of
    this framework that ever talks to CORTEX.
    """

    def __init__(
        self,
        name: str,
        threshold: float = 0.7,
        cortex_client=None,
        evaluation_params: Optional[list[str]] = None,
        input_source: str = "question",
        actual_source: str = "answer",
        context_source: Optional[str] = None,
        expected_source: Optional[str] = None,
        # HallucinationMetric uses LLMTestCase.context (ground truth), not retrieval_context.
        ground_truth_context_source: Optional[str] = None,
        tools_called_source: Optional[str] = None,
        expected_tools_source: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(name, threshold, **kwargs)
        self.cortex_llm = CortexDeepEvalLLM(cortex_client) if cortex_client else None
        self.evaluation_params = evaluation_params or ["input", "actual_output"]
        self.input_source = input_source
        self.actual_source = actual_source
        self.context_source = context_source
        self.expected_source = expected_source
        self.ground_truth_context_source = ground_truth_context_source
        self.tools_called_source = tools_called_source
        self.expected_tools_source = expected_tools_source

    def build_llm_test_case(self, test_case: TestCase, response: AgentResponse) -> LLMTestCase:
        retrieval = resolve_field(self.context_source, test_case, response) if self.context_source else None
        expected_output = resolve_field(self.expected_source, test_case, response) if self.expected_source else None
        ground_truth = (
            resolve_field(self.ground_truth_context_source, test_case, response)
            if self.ground_truth_context_source
            else None
        )
        tools_called = (
            _as_tool_calls(resolve_field(self.tools_called_source, test_case, response))
            if self.tools_called_source
            else None
        )
        expected_tools = (
            _as_tool_calls(resolve_field(self.expected_tools_source, test_case, response))
            if self.expected_tools_source
            else None
        )
        return LLMTestCase(
            input=str(resolve_field(self.input_source, test_case, response) or ""),
            actual_output=str(resolve_field(self.actual_source, test_case, response) or ""),
            retrieval_context=retrieval if isinstance(retrieval, list) else None,
            expected_output=str(expected_output) if expected_output else None,
            context=ground_truth if isinstance(ground_truth, list) else None,
            tools_called=tools_called,
            expected_tools=expected_tools,
        )

    def build_deepeval_metric(self):
        """Subclasses return a configured deepeval.metrics.* instance."""
        raise NotImplementedError

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        try:
            llm_test_case = self.build_llm_test_case(test_case, response)
            deepeval_metric = self.build_deepeval_metric()
            deepeval_metric.measure(llm_test_case)
            score = deepeval_metric.score or 0.0
            return MetricResult(
                name=self.name,
                score=score,
                threshold=self.threshold,
                passed=score >= self.threshold,
                reason=deepeval_metric.reason or "",
            )
        except Exception as exc:  # noqa: BLE001 - one bad metric shouldn't crash the whole run
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason=f"Metric errored: {exc}",
            )
