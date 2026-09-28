"""
A/B comparative evaluation — paired Candidate A vs Candidate B analysis.

Composes with existing runners/metrics; does not replace VERDICT or src.main.
"""

from src.comparison.engine import analyze_comparison
from src.comparison.models import ComparisonResult, ComparisonSpec, MetricVerdict
from src.comparison.runner import run_comparison

__all__ = [
    "ComparisonResult",
    "ComparisonSpec",
    "MetricVerdict",
    "analyze_comparison",
    "run_comparison",
]
