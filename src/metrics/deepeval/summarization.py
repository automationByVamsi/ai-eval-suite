from deepeval.metrics import SummarizationMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("summarization")
class SummarizationMetricAdapter(DeepEvalMetric):
    """
    Is the actual_output a faithful/complete summary of the input source text?

    For Fact Find: input_source=source_document (concatenated aggregate context),
    actual_source=answer (Customer FactFind Summary).
    """

    def __init__(self, *args, input_source: str = "source_document", **kwargs):
        """Default this metric to the source document field."""
        super().__init__(*args, input_source=input_source, **kwargs)

    def build_deepeval_metric(self):
        """Create the DeepEval summarization judge."""
        return SummarizationMetric(
            threshold=self.threshold, model=self.cortex_llm, include_reason=True
        )
