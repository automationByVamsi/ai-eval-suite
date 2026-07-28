from deepeval.metrics import HallucinationMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase


@METRIC_REGISTRY.register("hallucination")
class HallucinationMetricAdapter(DeepEvalMetric):
    """
    Fraction of answer claims contradicted by ground-truth context.

    DeepEval: lower is better (success when score <= threshold).
    Uses LLMTestCase.context via ground_truth_context_source.
    """

    def __init__(self, *args, ground_truth_context_source: str = "ground_truth_context", **kwargs):
        """Default this metric to the configured ground-truth context field."""
        super().__init__(*args, ground_truth_context_source=ground_truth_context_source, **kwargs)

    def build_deepeval_metric(self):
        """Create the DeepEval hallucination judge."""
        return HallucinationMetric(
            threshold=self.threshold, model=self.cortex_llm, include_reason=True
        )

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        """Use the inverted hallucination pass rule and handle missing context."""
        ground_truth = resolve_field(self.ground_truth_context_source, test_case, response)
        if not isinstance(ground_truth, list) or not ground_truth:
            return MetricResult(
                name=self.name,
                score=1.0,
                threshold=self.threshold,
                passed=False,
                reason="Skipped: no ground_truth_context available for hallucination.",
            )
        try:
            llm_test_case = self.build_llm_test_case(test_case, response)
            deepeval_metric = self.build_deepeval_metric()
            deepeval_metric.measure(llm_test_case)
            score = deepeval_metric.score or 0.0
            # Hallucination: passed when score <= threshold (inverted vs most metrics).
            passed = bool(getattr(deepeval_metric, "success", score <= self.threshold))
            return MetricResult(
                name=self.name,
                score=score,
                threshold=self.threshold,
                passed=passed,
                reason=deepeval_metric.reason or "",
            )
        except Exception as exc:  # noqa: BLE001
            return MetricResult(
                name=self.name,
                score=1.0,
                threshold=self.threshold,
                passed=False,
                reason=f"Metric errored: {exc}",
            )
