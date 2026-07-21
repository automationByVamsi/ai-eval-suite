from deepeval.metrics import ContextualRelevancyMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("contextual_relevancy")
class ContextualRelevancyMetricAdapter(DeepEvalMetric):
    """Is retrieval_context relevant to the input? (RAG retriever quality)."""

    def __init__(self, *args, context_source: str = "retrieval_context", **kwargs):
        super().__init__(*args, context_source=context_source, **kwargs)

    def build_deepeval_metric(self):
        return ContextualRelevancyMetric(
            threshold=self.threshold, model=self.cortex_llm, include_reason=True
        )
