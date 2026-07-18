"""
Generic name -> class registry, used for both agents and metrics.

Concrete adapters/metrics self-register at import time with a decorator:

    @AGENT_REGISTRY.register("replay")
    class ReplayAgentAdapter(BaseAgent):
        ...

The core framework never imports concrete adapters/metrics directly - it only
ever calls `registry.get(name)`. This is what makes adding a new agent or
metric a "no core change" operation.
"""

from src.core.exceptions import AgentNotFoundError, MetricNotFoundError


class Registry:
    """A simple name -> class map with a `.register()` decorator."""

    def __init__(self, kind: str, not_found_error: type[Exception] = KeyError):
        self._kind = kind
        self._not_found_error = not_found_error
        self._classes: dict[str, type] = {}

    def register(self, name: str):
        def decorator(cls: type) -> type:
            if name in self._classes and self._classes[name] is not cls:
                raise ValueError(f"{self._kind} '{name}' is already registered to {self._classes[name]}")
            self._classes[name] = cls
            return cls

        return decorator

    def get(self, name: str) -> type:
        if name not in self._classes:
            available = ", ".join(sorted(self._classes)) or "(none registered)"
            raise self._not_found_error(
                f"Unknown {self._kind} '{name}'. Available: {available}"
            )
        return self._classes[name]

    def is_registered(self, name: str) -> bool:
        return name in self._classes


# Two global registries used across the whole framework.
AGENT_REGISTRY = Registry("agent type", AgentNotFoundError)
METRIC_REGISTRY = Registry("metric type", MetricNotFoundError)
