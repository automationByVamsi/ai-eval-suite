"""Compare current distributions to a trusted baseline."""

from __future__ import annotations

from src.verdict.models import DiffRow, MetricAggregate


def diff_against_baseline(
    current: list[MetricAggregate],
    baseline: list[MetricAggregate],
    *,
    drop_threshold: float = 0.15,
) -> list[DiffRow]:
    """
    Compare current aggregates to baseline aggregates by pass rate.

    Flag a regression when pass_rate drops by more than drop_threshold
    (default 15pp). Ignores tiny noise from judge flakiness.
    """
    base_map = {(b.test_case_id, b.stage, b.name): b for b in baseline}
    rows: list[DiffRow] = []

    for cur in current:
        key = (cur.test_case_id, cur.stage, cur.name)
        base = base_map.get(key)
        if base is None:
            rows.append(
                DiffRow(
                    test_case_id=cur.test_case_id,
                    stage=cur.stage,
                    name=cur.name,
                    kind=cur.kind,
                    baseline_pass_rate=0.0,
                    current_pass_rate=cur.pass_rate,
                    delta=cur.pass_rate,
                    status="new",
                )
            )
            continue

        delta = cur.pass_rate - base.pass_rate
        if delta <= -drop_threshold:
            status = "regression"
        elif delta >= drop_threshold:
            status = "improved"
        else:
            status = "ok"

        rows.append(
            DiffRow(
                test_case_id=cur.test_case_id,
                stage=cur.stage,
                name=cur.name,
                kind=cur.kind,
                baseline_pass_rate=base.pass_rate,
                current_pass_rate=cur.pass_rate,
                delta=delta,
                status=status,
            )
        )
    return rows
