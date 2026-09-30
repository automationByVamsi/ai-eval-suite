"""
Load one agent's configuration: agents/<name>/agent.yaml.

Everything about an agent lives in its own folder:

    agents/<name>/
      agent.yaml       how to reach it, which metrics it uses, which suites run which metrics
      parser.py        optional: pull extra fields out of the trace + agent-specific checks
      client.py        optional: only for agents that are not Google ADK (see agents/_template)
      rubrics/*.md     optional: custom judge criteria
      testdata/<suite>/*.json
      synth/           optional: synthesizer settings (make goldens)

Used by: the runner, the synthesizer and the CLI. To add or change an agent you edit its folder,
never this file. This file only changes when agent.yaml gets a new top-level key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.core import env, paths
from src.core.exceptions import ConfigError
from src.metrics.library import validate_metric


@dataclass
class Suite:
    """One entry under `suites:` — which test data to run and which judges to run on it."""

    name: str
    testdata: Path                # folder of test case JSON files (sub-folders included)
    metrics: list[str]            # judge metrics to run; names defined under the agent's `metrics:`
    only: dict[str, Any]          # optional filter, e.g. {"metadata.approval_status": "APPROVED"}


@dataclass
class Agent:
    """An agent's agent.yaml, validated, with ${VAR} values filled in from the env files."""

    name: str
    folder: Path
    connection: dict[str, Any]              # passed as-is to the ADK client (or the agent's client.py)
    input_field: str                        # key in a test case's "input" that is sent to the agent
    message_template: str | None            # optional: wrap the input, e.g. "Look up {question}"
    metrics: dict[str, dict[str, Any]]      # metric name -> settings (threshold, rubric, ...)
    suites: dict[str, Suite]

    def suite(self, name: str) -> Suite:
        """A suite by name, or a ConfigError that lists the ones that exist."""
        if name not in self.suites:
            raise ConfigError(f"Agent '{self.name}' has no suite '{name}'. Suites: {sorted(self.suites)}")
        return self.suites[name]


def list_agents() -> list[str]:
    """Every folder under agents/ with an agent.yaml. Folders starting with _ (the template) are skipped."""
    return sorted(
        p.name for p in paths.AGENTS_DIR.iterdir()
        if (p / "agent.yaml").is_file() and not p.name.startswith("_")
    )


def load_agent(name: str) -> Agent:
    """
    Read and validate agents/<name>/agent.yaml.

    Mistakes (unknown metric keys, a suite using an undefined metric, a missing rubric file)
    raise ConfigError here, before anything runs — not halfway through a suite.
    """
    folder = paths.AGENTS_DIR / name
    path = folder / "agent.yaml"
    if not path.is_file():
        raise ConfigError(f"No agent '{name}'. Available: {list_agents()}")
    env.load_agent_env(name)
    raw = env.expand(yaml.safe_load(path.read_text()) or {})

    if "connection" not in raw:
        raise ConfigError(f"{path}: missing 'connection:' section (base_url, app_name, ...)")

    metrics: dict[str, dict[str, Any]] = {}
    for metric_name, spec in (raw.get("metrics") or {}).items():
        spec = dict(spec or {})
        if "rubric" in spec:
            # Rubric paths are written relative to the agent folder; store the full path.
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
            raise ConfigError(f"{path}: suite '{suite_name}' uses metrics not defined under metrics: {unknown}")
        suites[suite_name] = Suite(
            name=suite_name,
            testdata=folder / spec.get("testdata", f"testdata/{suite_name}"),
            metrics=wanted,
            only=dict(spec.get("only") or {}),
        )

    return Agent(
        name=name,
        folder=folder,
        connection=raw["connection"],
        input_field=raw.get("input_field", "question"),
        message_template=raw.get("message_template"),
        metrics=metrics,
        suites=suites,
    )
