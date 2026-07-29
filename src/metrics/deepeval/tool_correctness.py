from deepeval.metrics import ToolCorrectnessMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("tool_correctness")
class ToolCorrectnessMetricAdapter(DeepEvalMetric):
    """
    Did the agent call the expected tools (MCP / function calls)?

    Requires tools_called + expected_tools on the LLMTestCase (from ADK
    functionCall events and testdata expected.expected_tools).
    """

    def __init__(
        self,
        *args,
        tools_called_source: str = "tools_called",
        expected_tools_source: str = "expected_tools",
        should_consider_ordering: bool = False,
        should_exact_match: bool = False,
        **kwargs,
    ):
        """Configure where actual and expected tool calls come from."""
        super().__init__(
            *args,
            tools_called_source=tools_called_source,
            expected_tools_source=expected_tools_source,
            **kwargs,
        )
        self.should_consider_ordering = should_consider_ordering
        self.should_exact_match = should_exact_match

    def build_deepeval_metric(self):
        """Create the DeepEval tool correctness judge."""
        return ToolCorrectnessMetric(
            threshold=self.threshold,
            model=self.cortex_llm,
            include_reason=True,
            should_consider_ordering=self.should_consider_ordering,
            should_exact_match=self.should_exact_match,
        )
