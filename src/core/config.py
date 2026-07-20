"""
Thin helpers for reading YAML config files. No caching, no magic - a junior
engineer should be able to read this file top to bottom in a minute.
"""

from pathlib import Path
from typing import Any

import yaml

from src.core.exceptions import ConfigError


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a YAML mapping at the top level of {path}")
    return data


def load_agents_config(path: str | Path = "configs/agents.yaml") -> dict[str, Any]:
    """Returns the `agents:` mapping of agent_name -> {type, config, ...}."""
    data = load_yaml(path)
    agents = data.get("agents")
    if not agents:
        raise ConfigError(f"{path} must define a top-level 'agents:' mapping")
    return agents


def load_cortex_config(path: str | Path = "configs/cortex.yaml") -> dict[str, Any]:
    data = load_yaml(path)
    cortex = data.get("cortex")
    if not cortex:
        raise ConfigError(f"{path} must define a top-level 'cortex:' mapping")
    return cortex


def load_metrics_config(agent_profile: str, base_dir: str | Path = "configs/metrics") -> list[dict[str, Any]]:
    """Returns the `base_metrics:` list for a given agent profile, e.g. 'knowledge_agent'."""
    path = Path(base_dir) / f"{agent_profile}.yaml"
    data = load_yaml(path)
    return data.get("base_metrics", [])


def load_eval_config(agent_profile: str, eval_name: str, base_dir: str | Path = "configs/evaluations") -> dict[str, Any]:
    """Load configs/evaluations/<agent>/<eval_name>.yaml (e.g. a KA stage suite)."""
    path = Path(base_dir) / agent_profile / f"{eval_name}.yaml"
    return load_yaml(path)


# Backward-compatible alias (knowledge_agent stages use this name historically)
load_stage_config = load_eval_config
