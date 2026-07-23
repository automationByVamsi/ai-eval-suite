"""
VERDICT — reliability layer on top of existing HIVE stage contracts.

Wraps multi-run scoring + baseline regression diffs. Does not redefine
what "good" means; that stays in stage contracts / GEval rubrics.
"""

from src.verdict.models import MetricAggregate, VerdictReport
from src.verdict.runner import run_verdict

__all__ = ["MetricAggregate", "VerdictReport", "run_verdict"]
