"""
Importing this package registers every built-in metric with METRIC_REGISTRY.
MetricFactory imports this package once, on startup, so it never has to
import a concrete metric class by name.
"""

from src.metrics import (  # noqa: F401
    contextual_relevancy,
    correctness,
    custom_geval,
    faithfulness,
    hallucination,
    keyword_match,
    pegasus_faithfulness,
    relevance,
    summarization,
    task_completion,
    tool_correctness,
)
