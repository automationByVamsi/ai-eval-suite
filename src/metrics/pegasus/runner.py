"""Shared Pegasus runner — Factory picks strategy, this executes it."""

from __future__ import annotations

from typing import Any

from src.core.exceptions import MetricContractError
from src.metrics.pegasus.columns import fallback_columns, rag_dataframe, required_columns
from src.metrics.pegasus.factory import PegasusMetricFactory
from src.metrics.pegasus.fields import build_row, require_fields
from src.metrics.pegasus.llm import build_llm
from src.metrics.pegasus.results import result_from_pegasus
from src.metrics.pegasus.strategy import PegasusStrategy
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase

_MODE_TO_METHOD = {
    "pegasus": "pegasus",
    "pegasus_ragas": "ragas",
    "pegasus_deepeval": "deepeval",
}


def run_pegasus_metric(
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    """Resolve strategy from catalog cfg, enforce contract, call Pegasus."""
    strategy = PegasusMetricFactory.create(cfg)
    return _run_strategy(strategy, cfg, test_case, response, cortex_client=cortex_client)


def _run_strategy(
    strategy: PegasusStrategy,
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    name = str(cfg.get("name") or strategy.default_name or strategy.pegasus_class)
    threshold = float(cfg.get("threshold", 0.7))
    method = _method_from_cfg(cfg, strategy)

    needed = required_columns(
        strategy.metric_key,
        method,
        fallback=fallback_columns(
            strategy.required, strategy.required_by_method, method
        ),
    )

    row = build_row(tuple(needed), cfg, test_case, response)
    require_fields(test_case.test_case_id, name, row)

    return _call_pegasus(
        name=name,
        threshold=threshold,
        method=method,
        cortex_client=cortex_client,
        pegasus_class=strategy.pegasus_class,
        row=row,
    )


def _method_from_cfg(cfg: dict[str, Any], strategy: PegasusStrategy) -> str:
    mode = str(cfg.get("mode") or "pegasus").strip().lower()
    method = _MODE_TO_METHOD.get(mode, "pegasus")
    if strategy.allowed_methods and method not in strategy.allowed_methods:
        # e.g. AnswerCorrectness has no deepeval — coerce to pegasus.
        method = next(iter(sorted(strategy.allowed_methods)))
        if "pegasus" in strategy.allowed_methods:
            method = "pegasus"
    return method


def _call_pegasus(
    *,
    name: str,
    threshold: float,
    method: str,
    cortex_client: Any,
    pegasus_class: str,
    row: dict[str, Any],
) -> MetricResult:
    try:
        from pegasus.metrics import rag as pegasus_rag  # type: ignore

        metric_cls = getattr(pegasus_rag, pegasus_class)
        llm = build_llm(cortex_client)
        metric = metric_cls(llm=llm, method=method, threshold=threshold)
        df = rag_dataframe(row)
        return result_from_pegasus(name, threshold, metric.evaluate(df))
    except MetricContractError:
        raise
    except Exception as exc:  # noqa: BLE001
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason=f"Pegasus metric errored: {exc}",
        )
