"""
A deterministic, non-LLM metric - included on purpose to show that not every
plugged-in metric needs to go through CORTEX. Good template for cheap
sanity checks (e.g. "does the answer mention these required keywords?").
"""

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import BaseMetric
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase


@METRIC_REGISTRY.register("keyword_match")
class KeywordMatchMetric(BaseMetric):
    """threshold = minimum fraction of expected.keywords that must appear in the answer."""

    def __init__(self, name: str, threshold: float = 1.0, keywords_source: str = "keywords", **kwargs):
        """Configure which expected keyword list to check against the answer."""
        super().__init__(name, threshold, **kwargs)
        self.keywords_source = keywords_source

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        """Score the answer by how many required keywords it contains."""
        keywords = test_case.expected.get(self.keywords_source, [])
        if not keywords:
            return MetricResult(name=self.name, score=1.0, threshold=self.threshold, passed=True, reason="No keywords configured")

        answer_lower = response.answer.lower()
        matched = [kw for kw in keywords if kw.lower() in answer_lower]
        score = len(matched) / len(keywords)
        missing = sorted(set(keywords) - set(matched))
        reason = "All keywords present" if not missing else f"Missing keywords: {missing}"
        return MetricResult(name=self.name, score=score, threshold=self.threshold, passed=score >= self.threshold, reason=reason)
