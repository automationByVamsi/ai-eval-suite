"""Factory: catalog cfg → PegasusStrategy."""

from __future__ import annotations

from typing import Any

from src.metrics.pegasus.registry import DEFAULT_STRATEGY, PEGASUS_STRATEGIES
from src.metrics.pegasus.strategy import PegasusStrategy


class PegasusMetricFactory:
    """Resolve which Pegasus strategy to run for a catalog metric config."""

    @staticmethod
    def create(cfg: dict[str, Any]) -> PegasusStrategy:
        mtype = str(cfg.get("type") or cfg.get("name") or "").strip().lower()
        name = str(cfg.get("name") or "").strip().lower()
        for strategy in PEGASUS_STRATEGIES:
            if strategy.matches(mtype, name):
                return strategy
        return DEFAULT_STRATEGY
