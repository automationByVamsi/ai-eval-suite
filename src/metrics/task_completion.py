from deepeval.metrics import TaskCompletionMetric

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric


@METRIC_REGISTRY.register("task_completion")
class TaskCompletionMetricAdapter(DeepEvalMetric):
    """
    Single-turn DeepEval TaskCompletionMetric — did the agent accomplish the
    Fact Find goal (produce a usable summary for the complaint ref)?

    Complements MCPTaskCompletionMetric when MCP traces are absent: this one
    only needs input + actual_output (optionally tools via requires_trace).
    """

    def __init__(
        self,
        *args,
        task: str | None = None,
        input_source: str = "complaint_ref",
        **kwargs,
    ):
        super().__init__(*args, input_source=input_source, **kwargs)
        self.task = task or (
            "Given a complaint reference, gather customer facts and produce a "
            "Customer FactFind Summary for an advisor."
        )

    def build_deepeval_metric(self):
        return TaskCompletionMetric(
            threshold=self.threshold,
            task=self.task,
            model=self.cortex_llm,
            include_reason=True,
            async_mode=False,
        )
