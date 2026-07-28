"""
MetricFactory turns metric YAML configs into metric instances.

Agent invoke is not a factory — use src.clients.adk_client.AdkClient /
invoke_agent() instead (one ADK client for the whole lab).
"""

import json

import src.metrics  # noqa: F401 - import registers every built-in metric
from src.clients.cortex_client import CortexClient
from src.core.config import load_cortex_config, load_metrics_config
from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import BaseMetric


class MetricFactory:
    """Create and cache metric instances from YAML configs."""
    def __init__(self, cortex_config_path: str = "configs/cortex.yaml"):
        """Build the shared CORTEX client used by metrics."""
        self._cortex_client = CortexClient(load_cortex_config(cortex_config_path))
        self._cache: dict[str, BaseMetric] = {}

    def create(self, metric_config: dict) -> BaseMetric:
        """Create one metric instance from a config dict."""
        cache_key = json.dumps(metric_config, sort_keys=True)
        if cache_key in self._cache:
            return self._cache[cache_key]

        name = metric_config["name"]
        metric_type = metric_config.get("type", name)
        threshold = metric_config.get("threshold", 0.7)
        extra = {k: v for k, v in metric_config.items() if k not in {"name", "type", "threshold"}}

        metric_cls = METRIC_REGISTRY.get(metric_type)
        metric = metric_cls(name=name, threshold=threshold, cortex_client=self._cortex_client, **extra)
        self._cache[cache_key] = metric
        return metric

    def load_base_metrics(self, agent_profile: str) -> list[dict]:
        """Load the default metric list for an agent profile."""
        return load_metrics_config(agent_profile)
