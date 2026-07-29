"""
Pegasus-owned RAG metrics — Strategy + Factory.

Add a new Pegasus metric by registering one PegasusStrategy in registry.py.
Shared runner handles LLM, contract checks, DataFrame, and MetricResult mapping.
"""

from src.metrics.pegasus.factory import PegasusMetricFactory
from src.metrics.pegasus.runner import run_pegasus_metric

__all__ = ["PegasusMetricFactory", "run_pegasus_metric"]
