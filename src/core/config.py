"""
Thin helpers for reading YAML config files. No caching, no magic - a junior
engineer should be able to read this file top to bottom in a minute.

Loads `.env` (if present) and expands `${VAR}` / `${VAR:-default}` in values.

Knowledge Agent metrics use:
  configs/metrics/<profile>/catalog.yaml   — definitions (once)
  configs/evaluations/<profile>/<suite>.yaml — selection (judges + optional include)
"""

from pathlib import Path
from typing import Any

import yaml

from src.core.env import expand_env, load_dotenv
from src.core.exceptions import AgentNotFoundError, ConfigError


def load_yaml(path: str | Path) -> dict[str, Any]:
    load_dotenv()
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a YAML mapping at the top level of {path}")
    return expand_env(data)


def load_agents_config(path: str | Path = "configs/agents.yaml") -> dict[str, Any]:
    """Returns the `agents:` mapping of agent_name -> config."""
    data = load_yaml(path)
    agents = data.get("agents")
    if not agents:
        raise ConfigError(f"{path} must define a top-level 'agents:' mapping")
    return agents


def get_agent_config(
    agent_name: str,
    path: str | Path = "configs/agents.yaml",
) -> dict[str, Any]:
    """One agent's config dict (ADK URL, app_name, metrics_profile, ...)."""
    agents = load_agents_config(path)
    if agent_name not in agents:
        available = ", ".join(sorted(agents)) or "(none)"
        raise AgentNotFoundError(
            f"Unknown agent '{agent_name}' in {path}. Available: {available}"
        )
    entry = agents[agent_name]
    if not isinstance(entry, dict):
        raise ConfigError(f"Agent '{agent_name}' config must be a mapping")
    # Flat shape (preferred). Legacy nested `config:` still accepted.
    if "config" in entry and isinstance(entry["config"], dict):
        merged = {**entry["config"], **{k: v for k, v in entry.items() if k != "config"}}
        return merged
    return dict(entry)


def agent_metrics_profile(
    agent_name: str,
    path: str | Path = "configs/agents.yaml",
) -> str:
    cfg = get_agent_config(agent_name, path=path)
    return str(cfg.get("metrics_profile") or agent_name)


def load_cortex_config(path: str | Path = "configs/cortex.yaml") -> dict[str, Any]:
    data = load_yaml(path)
    cortex = data.get("cortex")
    if not cortex:
        raise ConfigError(f"{path} must define a top-level 'cortex:' mapping")
    return cortex


def load_metric_catalog(
    agent_profile: str,
    base_dir: str | Path = "configs/metrics",
) -> dict[str, dict[str, Any]]:
    """
    Load configs/metrics/<profile>/catalog.yaml → {metric_name: definition}.

    Each definition is a dict suitable for MetricFactory.create (name injected).
    """
    path = Path(base_dir) / agent_profile / "catalog.yaml"
    data = load_yaml(path)
    raw = data.get("metrics")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"{path} must define a non-empty top-level 'metrics:' mapping")

    catalog: dict[str, dict[str, Any]] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            raise ConfigError(f"Metric '{name}' in {path} must be a mapping")
        entry = dict(cfg)
        entry["name"] = name
        catalog[name] = entry
    return catalog


def catalog_default_suite(
    agent_profile: str,
    base_dir: str | Path = "configs/metrics",
) -> str:
    path = Path(base_dir) / agent_profile / "catalog.yaml"
    data = load_yaml(path)
    return str(data.get("default_suite") or "e2e")


def has_metric_catalog(
    agent_profile: str,
    base_dir: str | Path = "configs/metrics",
) -> bool:
    return (Path(base_dir) / agent_profile / "catalog.yaml").exists()


def load_metrics_config(
    agent_profile: str,
    base_dir: str | Path = "configs/metrics",
) -> list[dict[str, Any]]:
    """
    Default metric list for an agent profile.

    - If configs/metrics/<profile>/catalog.yaml exists: resolve default_suite
      (usually e2e) via evaluations/<profile>/<suite>.yaml.
    - Else legacy: configs/metrics/<profile>.yaml → base_metrics: [...]
    """
    if has_metric_catalog(agent_profile, base_dir=base_dir):
        suite = catalog_default_suite(agent_profile, base_dir=base_dir)
        return resolve_suite_metrics(agent_profile, suite)

    path = Path(base_dir) / f"{agent_profile}.yaml"
    data = load_yaml(path)
    return data.get("base_metrics", [])


def load_eval_config(
    agent_profile: str,
    eval_name: str,
    base_dir: str | Path = "configs/evaluations",
) -> dict[str, Any]:
    """Load configs/evaluations/<agent>/<eval_name>.yaml (suite or legacy eval)."""
    path = Path(base_dir) / agent_profile / f"{eval_name}.yaml"
    return load_yaml(path)


def _suite_judge_names(
    agent_profile: str,
    suite_name: str,
    *,
    evals_dir: str | Path = "configs/evaluations",
    _seen: set[str] | None = None,
) -> list[str]:
    """Collect judge metric names from a suite, following `include:` (no cycles)."""
    seen = _seen if _seen is not None else set()
    if suite_name in seen:
        raise ConfigError(f"Suite include cycle involving '{suite_name}'")
    seen.add(suite_name)

    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    names: list[str] = []

    for inc in suite.get("include") or []:
        names.extend(
            _suite_judge_names(
                agent_profile,
                str(inc),
                evals_dir=evals_dir,
                _seen=seen,
            )
        )

    for item in suite.get("judges") or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        else:
            raise ConfigError(
                f"Suite '{suite_name}' judges entry must be a name or {{name: ...}}, got {item!r}"
            )

    for item in suite.get("judge_metrics") or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))

    out: list[str] = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


def resolve_suite_metrics(
    agent_profile: str,
    suite_name: str,
    *,
    metrics_dir: str | Path = "configs/metrics",
    evals_dir: str | Path = "configs/evaluations",
) -> list[dict[str, Any]]:
    """
    Resolve a suite to full metric configs.

    Prefers catalog definitions. If the suite still uses legacy inline
    `judge_metrics:` dicts (and no catalog), returns those dicts as-is.
    """
    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    legacy_inline = suite.get("judge_metrics") or []
    inline_by_name = {
        m["name"]: m
        for m in legacy_inline
        if isinstance(m, dict) and m.get("name") and m.get("type")
    }

    names = _suite_judge_names(agent_profile, suite_name, evals_dir=evals_dir)

    if has_metric_catalog(agent_profile, base_dir=metrics_dir):
        catalog = load_metric_catalog(agent_profile, base_dir=metrics_dir)
        resolved: list[dict[str, Any]] = []
        missing: list[str] = []
        for name in names:
            if name in catalog:
                resolved.append(dict(catalog[name]))
            elif name in inline_by_name:
                resolved.append(dict(inline_by_name[name]))
            else:
                missing.append(name)
        if missing:
            raise ConfigError(
                f"Suite '{suite_name}' references unknown metrics {missing}. "
                f"Catalog has: {sorted(catalog)}"
            )
        return resolved

    if inline_by_name:
        return [dict(inline_by_name[n]) for n in names if n in inline_by_name]

    raise ConfigError(
        f"No metric catalog for '{agent_profile}' and suite '{suite_name}' "
        f"has no inline judge_metrics definitions"
    )


def suite_deterministic_names(
    agent_profile: str,
    suite_name: str,
    *,
    evals_dir: str | Path = "configs/evaluations",
    _seen: set[str] | None = None,
) -> list[str]:
    """Collect `deterministic:` check names from a suite (follows include:)."""
    seen = _seen if _seen is not None else set()
    if suite_name in seen:
        raise ConfigError(f"Suite include cycle involving '{suite_name}'")
    seen.add(suite_name)

    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    names: list[str] = []
    for inc in suite.get("include") or []:
        names.extend(
            suite_deterministic_names(
                agent_profile,
                str(inc),
                evals_dir=evals_dir,
                _seen=seen,
            )
        )
    for item in suite.get("deterministic") or []:
        names.append(str(item))

    out: list[str] = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


# Backward-compatible alias (knowledge_agent stages use this name historically)
load_stage_config = load_eval_config
