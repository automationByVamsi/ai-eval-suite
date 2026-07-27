"""Unit tests for VERDICT aggregate + baseline diff (no CORTEX / traces)."""

from src.verdict.aggregate import aggregate_reps
from src.verdict.diff import diff_against_baseline
from src.verdict.models import CheckObservation, MetricAggregate, RepResult


def test_aggregate_pass_rate():
    reps = []
    for i in range(5):
        reps.append(
            RepResult(
                test_case_id="TC_001",
                stage="sanity",
                rep=i,
                passed=i == 0,
                checks=[
                    CheckObservation(
                        name="answer_non_empty",
                        kind="deterministic",
                        passed=(i == 0),
                    )
                ],
            )
        )
    aggs = aggregate_reps(reps)
    assert len(aggs) == 1
    assert aggs[0].pass_rate == 0.2
    assert aggs[0].single_run_label == "FLAKY"


def test_diff_flags_regression():
    baseline = [
        MetricAggregate(
            test_case_id="TC_001",
            stage="sanity",
            name="answer_non_empty",
            kind="deterministic",
            n=5,
            pass_rate=1.0,
        )
    ]
    current = [
        MetricAggregate(
            test_case_id="TC_001",
            stage="sanity",
            name="answer_non_empty",
            kind="deterministic",
            n=5,
            pass_rate=0.4,
        )
    ]
    rows = diff_against_baseline(current, baseline, drop_threshold=0.15)
    assert len(rows) == 1
    assert rows[0].status == "regression"
    assert rows[0].delta == -0.6
