"""
AgentFactory and MetricFactory are the ONLY code in this framework that
touches AGENT_REGISTRY / METRIC_REGISTRY directly. They read YAML config and
turn it into configured, cached objects. Nothing else should ever import an
agent or metric class by name - go through these factories instead.
"""

import json

import src.agents  # noqa: F401 - import registers every built-in agent adapter
import src.metrics  # noqa: F401 - import registers every built-in metric
from src.agents.base_agent import BaseAgent
from src.clients.cortex_client import CortexClient
from src.core.config import load_agents_config, load_cortex_config, load_metrics_config
from src.core.exceptions import AgentNotFoundError
from src.core.registry import AGENT_REGISTRY, METRIC_REGISTRY
from src.metrics.base_metric import BaseMetric


class AgentFactory:
    def __init__(self, agents_config_path: str = "configs/agents.yaml"):
        self._agents_config = load_agents_config(agents_config_path)
        self._cache: dict[str, BaseAgent] = {}

    def create(self, agent_name: str) -> BaseAgent:
        if agent_name in self._cache:
            return self._cache[agent_name]
        if agent_name not in self._agents_config:
            raise AgentNotFoundError(f"'{agent_name}' is not defined in agents.yaml")

        entry = self._agents_config[agent_name]
        agent_cls = AGENT_REGISTRY.get(entry["type"])
        agent = agent_cls(config=entry.get("config", {}))
        self._cache[agent_name] = agent
        return agent

    def metrics_profile(self, agent_name: str) -> str:
        """Which configs/metrics/<profile>.yaml file backs this agent's default metrics."""
        entry = self._agents_config.get(agent_name, {})
        return entry.get("metrics_profile", agent_name)


class MetricFactory:
    def __init__(self, cortex_config_path: str = "configs/cortex.yaml"):
        self._cortex_client = CortexClient(load_cortex_config(cortex_config_path))
        self._cache: dict[str, BaseMetric] = {}

    def create(self, metric_config: dict) -> BaseMetric:
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
        return load_metrics_config(agent_profile)
