"""
Load one agent's configuration: agents/<name>/agent.yaml.

Everything about an agent lives in its own folder:

    agents/<name>/
      agent.yaml       how to reach it, which metrics it uses, which suites run which metrics and checks
      fields.yaml      optional: the fields evaluation reads from the trace (see src/fields/extract.py)
      lookups.py       optional: functions that look values up outside the trace by id (src/fields/lookup.py)
      parser.py        optional: Python for what fields.yaml / checks: can't express
      client.py        optional: only for agents that are not Google ADK (see agents/_template)
      rubrics/*.md     optional: custom judge criteria
      testdata/<suite>/*.json
      synth/           optional: synthesizer settings (make goldens)
      importers/*.yaml optional: spreadsheet column mappings (make import-cases)

Used by: the runner, the synthesizer and the CLI. To add or change an agent you edit its folder,
never this file. This file only changes when agent.yaml gets a new top-level key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core import env, paths
from src.core.exceptions import ConfigError
from src.fields import checks as yaml_checks
from src.fields import extract
from src.metrics.library import validate_metric


@dataclass
class Suite:
    """One entry under `suites:` — which test data to run and which judges to run on it."""

    name: str
    testdata: Path                # folder of test case JSON files (sub-folders included)
    metrics: list[str]            # judge metrics to run; names defined under the agent's `metrics:`
    only: dict[str, Any]          # optional filter, e.g. {"metadata.approval_status": "APPROVED"}
    checks: list[str] | None = None   # deterministic checks to run: None = all, [] = none, else names/groups


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
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)   # fields.yaml: what to read from traces
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)   # checks: in agent.yaml
    message_fields: dict[str, str] = field(default_factory=dict)      # message: send input as JSON (see below)

    def checks_for(self, suite: Suite) -> dict[str, dict[str, Any]]:
        """The checks: from agent.yaml that this suite runs (a group name selects its whole group)."""
        if suite.checks is None:
            return dict(self.checks)
        wanted = set(suite.checks)
        return {n: s for n, s in self.checks.items() if n in wanted or s.get("group") in wanted}

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
        json_path = (spec.get("options") or {}).get("json_path")
        if json_path:                      # Pegasus custom criteria file, written relative to the agent folder
            criteria = folder / json_path
            if not criteria.is_file():
                raise ConfigError(f"{path}: options.json_path for '{metric_name}' not found: {criteria}")
            spec["options"] = {**spec["options"], "json_path": str(criteria)}
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
            checks=_suite_checks(spec.get("checks", "all"), f"{path}: suite '{suite_name}'"),
        )

    fields_file = folder / "fields.yaml"
    fields = {}
    if fields_file.is_file():
        fields = extract.validate((yaml.safe_load(fields_file.read_text()) or {}).get("fields") or {},
                                  str(fields_file), folder)

    checks = yaml_checks.validate(raw.get("checks") or {}, str(path))
    known = {*checks, *(s.get("group") for s in checks.values() if s.get("group")), *BASIC_CHECKS}
    for suite in suites.values():
        unknown = sorted(set(suite.checks or []) - known)
        if unknown:
            raise ConfigError(f"{path}: suite '{suite.name}' checks: {unknown} are neither checks nor groups. "
                              f"Known: {sorted(known)}")

    return Agent(
        name=name,
        folder=folder,
        connection=raw["connection"],
        input_field=raw.get("input_field", "question"),
        message_template=raw.get("message_template"),
        message_fields=_message_fields(raw.get("message"), str(path)),
        metrics=metrics,
        suites=suites,
        fields=fields,
        checks=checks,
    )


# The checks every agent gets (runner._standard_checks), selectable by name or as the group "basic".
BASIC_CHECKS = ("basic", "answer_non_empty", "keywords")


def _message_fields(spec: Any, where: str) -> dict[str, str]:
    """
    `message: {format: json, fields: {<key the agent expects>: <key in the test case input>}}`
    sends the input as a JSON object inside the message text, e.g. for the Knowledge Agent
        {"query": "How do I ...?", "question_type": "how"}
    Inputs a case doesn't have are left out; a case with only the main input still sends plain text.
    """
    if not spec:
        return {}
    if not isinstance(spec, dict) or spec.get("format") != "json" or not isinstance(spec.get("fields"), dict):
        raise ConfigError(f"{where}: message: must be {{format: json, fields: {{agent_key: input_key}}}}")
    return {str(k): str(v) for k, v in spec["fields"].items()}


def _suite_checks(value: Any, where: str) -> list[str] | None:
    """A suite's `checks:` -> None (all), [] (none) or the listed names."""
    if value in ("all", None):
        return None
    if value in ("none", [], False):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: checks: must be all, none, or a list of check / group names")
    return list(value)
