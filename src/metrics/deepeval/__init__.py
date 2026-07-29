"""
DeepEval-backed metrics (our wrappers around DeepEval classes).

Importing this package registers every metric with METRIC_REGISTRY.
"""

from src.metrics.deepeval import (  # noqa: F401
    contextual_relevancy,
    correctness,
    custom_geval,
    faithfulness,
    hallucination,
    keyword_match,
    relevance,
    summarization,
    task_completion,
    tool_correctness,
)
