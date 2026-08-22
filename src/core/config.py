"""
Thin helpers for reading YAML config files. No caching, no magic - a junior
engineer should be able to read this file top to bottom in a minute.

Loads `.env` (if present) and expands `${VAR}` / `${VAR:-default}` in values.

Knowledge Agent metrics use:
  configs/metrics/<profile>/catalog.yaml   — definitions (once)
  configs/evaluations/<profile>/<suite>.yaml — selection (judges + optional include)

Suite YAML may set ``mode:`` (default pegasus). Each judge can override with
``{name: …, mode: …}``. Catalog ``backends:`` (or type inference) decides
whether a preferred mode applies or falls back to deepeval for customs.
"""

from pathlib import Path
from typing import Any

import yaml

from src.core.env import expand_env, load_dotenv
from src.core.exceptions import AgentNotFoundError, ConfigError
from src.core.metric_mode import (
    DEFAULT_SUITE_MODE,
    apply_resolved_mode,
    preferred_suite_mode,
    resolve_metric_mode,
)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load one YAML file, expand env vars, and require a mapping root."""
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
    """Return the metrics profile name for an agent."""
    cfg = get_agent_config(agent_name, path=path)
    return str(cfg.get("metrics_profile") or agent_name)


def load_cortex_config(path: str | Path = "configs/cortex.yaml") -> dict[str, Any]:
    """Return the `cortex:` config block from the YAML file."""
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
    """Read the default suite name from a metric catalog."""
    path = Path(base_dir) / agent_profile / "catalog.yaml"
    data = load_yaml(path)
    return str(data.get("default_suite") or "e2e")


def has_metric_catalog(
    agent_profile: str,
    base_dir: str | Path = "configs/metrics",
) -> bool:
    """Return whether this agent profile has a catalog.yaml file."""
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


def _parse_judge_entry(
    item: Any,
    *,
    suite_name: str,
) -> tuple[str, str | None]:
    """Return (metric_name, optional per-judge mode override)."""
    if isinstance(item, str):
        return item, None
    if isinstance(item, dict) and item.get("name"):
        override = item.get("mode")
        return str(item["name"]), (str(override) if override is not None else None)
    raise ConfigError(
        f"Suite '{suite_name}' judges entry must be a name or "
        f"{{name: ..., mode?: ...}}, got {item!r}"
    )


def _suite_judges(
    agent_profile: str,
    suite_name: str,
    *,
    evals_dir: str | Path = "configs/evaluations",
    _seen: set[str] | None = None,
) -> list[tuple[str, str | None]]:
    """
    Collect (judge_name, mode_override) from a suite, following ``include:``.

    First occurrence of a name wins (include order, then local judges).
    """
    seen = _seen if _seen is not None else set()
    if suite_name in seen:
        raise ConfigError(f"Suite include cycle involving '{suite_name}'")
    seen.add(suite_name)

    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    entries: list[tuple[str, str | None]] = []

    for inc in suite.get("include") or []:
        entries.extend(
            _suite_judges(
                agent_profile,
                str(inc),
                evals_dir=evals_dir,
                _seen=seen,
            )
        )

    for item in suite.get("judges") or []:
        entries.append(_parse_judge_entry(item, suite_name=suite_name))

    for item in suite.get("judge_metrics") or []:
        entries.append(_parse_judge_entry(item, suite_name=suite_name))

    out: list[tuple[str, str | None]] = []
    seen_names: set[str] = set()
    for name, override in entries:
        if name in seen_names:
            continue
        seen_names.add(name)
        out.append((name, override))
    return out


def _suite_judge_names(
    agent_profile: str,
    suite_name: str,
    *,
    evals_dir: str | Path = "configs/evaluations",
    _seen: set[str] | None = None,
) -> list[str]:
    """Collect judge metric names from a suite, following `include:` (no cycles)."""
    return [
        name
        for name, _ in _suite_judges(
            agent_profile, suite_name, evals_dir=evals_dir, _seen=_seen
        )
    ]


def _suite_mode(
    agent_profile: str,
    suite_name: str,
    *,
    evals_dir: str | Path = "configs/evaluations",
) -> str | None:
    """
    Effective suite-level mode for ``suite_name``.

    Child suite ``mode:`` wins over included parents when set; otherwise the
    first non-empty mode from ``include:`` order is used.
    """
    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    own = suite.get("mode")
    if own is not None and str(own).strip():
        return str(own).strip()

    for inc in suite.get("include") or []:
        inherited = _suite_mode(agent_profile, str(inc), evals_dir=evals_dir)
        if inherited:
            return inherited
    return None


def _catalog_lookup(
    catalog: dict[str, dict[str, Any]],
    name: str,
) -> tuple[dict[str, Any], str | None] | None:
    """
    Find a catalog metric by name.

    Legacy ``*_pegasus`` aliases map to the base metric and imply pegasus mode.
    """
    if name in catalog:
        return dict(catalog[name]), None
    if name.endswith("_pegasus"):
        base = name[: -len("_pegasus")]
        if base in catalog:
            return dict(catalog[base]), "pegasus"
        # e.g. already-canonical names were only registered with a suffix historically
        if name in catalog:
            return dict(catalog[name]), "pegasus"
    return None


def resolve_suite_metrics(
    agent_profile: str,
    suite_name: str,
    *,
    metrics_dir: str | Path = "configs/metrics",
    evals_dir: str | Path = "configs/evaluations",
) -> list[dict[str, Any]]:
    """
    Resolve a suite to full metric configs with effective ``mode`` set.

    Prefers catalog definitions. If the suite still uses legacy inline
    `judge_metrics:` dicts (and no catalog), returns those dicts as-is
    (still applying suite mode resolution when possible).
    """
    suite = load_eval_config(agent_profile, suite_name, base_dir=evals_dir)
    legacy_inline = suite.get("judge_metrics") or []
    inline_by_name = {
        m["name"]: m
        for m in legacy_inline
        if isinstance(m, dict) and m.get("name") and m.get("type")
    }

    judges = _suite_judges(agent_profile, suite_name, evals_dir=evals_dir)
    suite_preferred = preferred_suite_mode(
        _suite_mode(agent_profile, suite_name, evals_dir=evals_dir)
        or suite.get("mode")
        or DEFAULT_SUITE_MODE
    )

    if has_metric_catalog(agent_profile, base_dir=metrics_dir):
        catalog = load_metric_catalog(agent_profile, base_dir=metrics_dir)
        resolved: list[dict[str, Any]] = []
        missing: list[str] = []
        for name, judge_override in judges:
            hit = _catalog_lookup(catalog, name)
            if hit is not None:
                cfg, alias_mode = hit
                if name.endswith("_pegasus") and name not in catalog:
                    cfg["name"] = name[: -len("_pegasus")]
                override = judge_override or alias_mode
                mode = resolve_metric_mode(
                    suite_preferred, cfg, judge_override=override
                )
                resolved.append(apply_resolved_mode(cfg, mode))
            elif name in inline_by_name:
                cfg = dict(inline_by_name[name])
                mode = resolve_metric_mode(
                    suite_preferred, cfg, judge_override=judge_override
                )
                resolved.append(apply_resolved_mode(cfg, mode))
            else:
                missing.append(name)
        if missing:
            raise ConfigError(
                f"Suite '{suite_name}' references unknown metrics {missing}. "
                f"Catalog has: {sorted(catalog)}"
            )
        return resolved

    if inline_by_name:
        resolved = []
        for name, judge_override in judges:
            if name not in inline_by_name:
                continue
            cfg = dict(inline_by_name[name])
            mode = resolve_metric_mode(
                suite_preferred, cfg, judge_override=judge_override
            )
            resolved.append(apply_resolved_mode(cfg, mode))
        return resolved

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
