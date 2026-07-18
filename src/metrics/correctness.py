from deepeval.metrics import GEval
from deepeval.test_case import SingleTurnParams

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


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
