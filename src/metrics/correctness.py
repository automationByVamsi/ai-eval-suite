from deepeval.metrics import GEval
from deepeval.test_case import SingleTurnParams

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase


@METRIC_REGISTRY.register("correctness")
class CorrectnessMetric(DeepEvalMetric):
    """Is the answer factually correct and complete compared to the expected answer?"""

    def __init__(self, *args, expected_source: str = "expected_answer", **kwargs):
        super().__init__(*args, expected_source=expected_source, **kwargs)

    def build_deepeval_metric(self):
        return GEval(
            name="Correctness",
            criteria=(
                "Determine whether the actual output is factually correct and complete "
                "compared to the expected output, for the given input."
            ),
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            model=self.cortex_llm,
            threshold=self.threshold,
        )

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        expected_output = resolve_field(self.expected_source, test_case, response)
        if not expected_output or not str(expected_output).strip():
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason="Skipped: no expected answer configured for correctness.",
            )
        return super().evaluate(test_case, response)
