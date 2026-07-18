from deepeval.metrics import FaithfulnessMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("faithfulness")
class FaithfulnessMetricAdapter(DeepEvalMetric):
    """Does the answer stick to the retrieved context (no hallucination)?"""

    def __init__(self, *args, context_source: str = "retrieval_context", **kwargs):
        super().__init__(*args, context_source=context_source, **kwargs)

    def build_deepeval_metric(self):
        return FaithfulnessMetric(threshold=self.threshold, model=self.cortex_llm, include_reason=True)
