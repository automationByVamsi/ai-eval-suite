from deepeval.metrics import AnswerRelevancyMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("relevance")
class RelevanceMetric(DeepEvalMetric):
    """Is the answer relevant to the question? Scored by DeepEval's AnswerRelevancyMetric."""

    def build_deepeval_metric(self):
        return AnswerRelevancyMetric(threshold=self.threshold, model=self.cortex_llm, include_reason=True)
