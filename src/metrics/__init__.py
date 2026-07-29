"""
Metric packages:

  src/metrics/deepeval/  — our DeepEval wrappers (METRIC_REGISTRY)
  src/metrics/pegasus/   — Pegasus RAG strategies (Factory + shared runner)

Importing this package registers DeepEval metrics for MetricFactory.
"""

import src.metrics.deepeval  # noqa: F401
