from deepeval.metrics import ContextualRelevancyMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase


@METRIC_REGISTRY.register("contextual_relevancy")
class ContextualRelevancyMetricAdapter(DeepEvalMetric):
    """Is retrieval_context relevant to the input? (RAG retriever quality)."""

    def __init__(self, *args, context_source: str = "retrieval_context", **kwargs):
        super().__init__(*args, context_source=context_source, **kwargs)

    def build_deepeval_metric(self):
        return ContextualRelevancyMetric(
            threshold=self.threshold, model=self.cortex_llm, include_reason=True
        )

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        context = resolve_field(self.context_source, test_case, response)
        if not isinstance(context, list) or not context:
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason="Skipped: no retrieval_context available for contextual relevancy.",
            )
        return super().evaluate(test_case, response)
