"""
Read an agent's folder: agents/<name>/agent.yaml (+ values from .env).

Everything about one agent lives in its own folder:

    agents/<name>/
      agent.yaml     how to reach it, which metrics it uses, which suites run which metrics
      parser.py      optional: pull fields out of the trace + agent-specific checks
      client.py      optional: only for agents that are not Google ADK (see agents/_template)
      rubrics/*.md   optional: custom judge criteria
      testdata/<suite>/*.json

`${VAR}` and `${VAR:-default}` in agent.yaml are filled from the environment / .env.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
OUTPUTS_DIR = ROOT / "outputs"
BASELINES_DIR = ROOT / "baselines"

load_dotenv(ROOT / ".env")

_ENV_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


class ConfigError(Exception):
    """agent.yaml or a test case is missing something the framework needs."""


@dataclass
class Suite:
    name: str
    testdata: Path
    metrics: list[str]
    only: dict[str, Any]


@dataclass
class Agent:
    name: str
    folder: Path
    connection: dict[str, Any]
    input_field: str
    message_template: str | None
    metrics: dict[str, dict[str, Any]]
    suites: dict[str, Suite]

    def suite(self, name: str) -> Suite:
        if name not in self.suites:
            raise ConfigError(f"Agent '{self.name}' has no suite '{name}'. Suites: {sorted(self.suites)}")
        return self.suites[name]


def list_agents() -> list[str]:
    """Every folder under agents/ that has an agent.yaml (folders starting with _ are templates)."""
    return sorted(
        p.name for p in AGENTS_DIR.iterdir()
        if (p / "agent.yaml").is_file() and not p.name.startswith("_")
    )


def load_agent(name: str) -> Agent:
    """Load and validate agents/<name>/agent.yaml."""
    from evalkit.judges import validate_metric  # local import: judges imports heavy libraries

    folder = AGENTS_DIR / name
    path = folder / "agent.yaml"
    if not path.is_file():
        raise ConfigError(f"No agent '{name}'. Available: {list_agents()}")
    raw = _expand_env(yaml.safe_load(path.read_text()) or {})

    metrics: dict[str, dict[str, Any]] = {}
    for metric_name, spec in (raw.get("metrics") or {}).items():
        spec = dict(spec or {})
        if "rubric" in spec:
            rubric = folder / spec["rubric"]
            if not rubric.is_file():
                raise ConfigError(f"{path}: rubric for '{metric_name}' not found: {rubric}")
            spec["rubric"] = str(rubric)
        validate_metric(metric_name, spec, where=str(path))
        metrics[metric_name] = spec

    suites: dict[str, Suite] = {}
    for suite_name, spec in (raw.get("suites") or {}).items():
        spec = spec or {}
        wanted = list(spec.get("metrics") or [])
        unknown = [m for m in wanted if m not in metrics]
        if unknown:
            raise ConfigError(f"{path}: suite '{suite_name}' uses undefined metrics {unknown}")
        suites[suite_name] = Suite(
            name=suite_name,
            testdata=folder / spec.get("testdata", f"testdata/{suite_name}"),
            metrics=wanted,
            only=dict(spec.get("only") or {}),
        )

    if "connection" not in raw:
        raise ConfigError(f"{path}: missing 'connection:' section (base_url, app_name, ...)")
    return Agent(
        name=name,
        folder=folder,
        connection=raw["connection"],
        input_field=raw.get("input_field", "question"),
        message_template=raw.get("message_template"),
        metrics=metrics,
        suites=suites,
    )


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        # Like the shell: ${VAR:-default} uses the default when VAR is unset *or empty*.
        return _ENV_VAR.sub(lambda m: os.environ.get(m.group(1)) or m.group(2) or "", value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value
