"""Turn repetition observations into pass-rate / score distributions."""

from __future__ import annotations

import math
from collections import defaultdict

from src.verdict.models import MetricAggregate, RepResult


def _std(values: list[float]) -> float:
    """Return the sample standard deviation for numeric scores."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def aggregate_reps(reps: list[RepResult]) -> list[MetricAggregate]:
    """Group by (case, stage, check name) and compute pass_rate + score stats."""
    buckets: dict[tuple[str, str, str, str], list[tuple[bool, float | None]]] = defaultdict(list)

    for rep in reps:
        for check in rep.checks:
            key = (rep.test_case_id, rep.stage, check.name, check.kind)
            buckets[key].append((check.passed, check.score))

    out: list[MetricAggregate] = []
    for (case_id, stage, name, kind), rows in sorted(buckets.items()):
        scores = [s for _, s in rows if s is not None]
        passes = sum(1 for ok, _ in rows if ok)
        n = len(rows)
        out.append(
            MetricAggregate(
                test_case_id=case_id,
                stage=stage,
                name=name,
                kind=kind,
                n=n,
                pass_rate=passes / n if n else 0.0,
                mean_score=(sum(scores) / len(scores)) if scores else None,
                std_score=_std(scores) if scores else None,
                scores=scores,
            )
        )
    return out
