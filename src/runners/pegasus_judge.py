"""
Thin entry for evaluate() — Pegasus logic lives in src.metrics.pegasus.

  from src.runners.pegasus_judge import run_pegasus_metric
"""

from src.metrics.pegasus import run_pegasus_metric

__all__ = ["run_pegasus_metric"]
