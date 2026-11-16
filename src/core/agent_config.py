"""Load and validate one agent's config: agents/<name>/agent.yaml plus its checks.yaml, fields.yaml
and exporters/review_sheet.yaml.

Raises ConfigError on mistakes before anything runs.
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
    """One entry under `suites:`: which test data to run and which judges and checks to run on it."""

    name: str
    testdata: Path                # folder of test case JSON files (sub-folders included)
    metrics: list[str]
    only: dict[str, Any]          # optional filter, e.g. {"metadata.approval_status": "APPROVED"}
    checks: list[str] | None = None   # None = all, [] = none, else names/groups
    targets: dict[str, float] = field(default_factory=dict)   # release targets: pass rate per judge / check
    traces: str = ""              # whose saved traces OFFLINE=1 replays (default: this suite's own)


@dataclass
class Agent:
    """An agent's validated agent.yaml, with ${VAR} values filled in from the env files."""

    name: str
    folder: Path
    connection: dict[str, Any]              # passed as-is to the ADK client (or the agent's client.py)
    input_field: str                        # key in a test case's "input" that is sent to the agent
    message_template: str | None            # optional: wrap the input, e.g. "Look up {question}"
    metrics: dict[str, dict[str, Any]]
    suites: dict[str, Suite]
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    message_fields: dict[str, str] = field(default_factory=dict)      # send input as JSON; see _message_fields
    consistency: dict[str, Any] = field(default_factory=dict)         # rules for REPS > 1
    review_sheet: dict[str, dict] = field(default_factory=dict)       # SME review sheet: {group: {heading: value}}

    def checks_for(self, suite: Suite) -> dict[str, dict[str, Any]]:
        """Return the agent's checks this suite runs; a group name selects its whole group."""
        if suite.checks is None:
            return dict(self.checks)
        wanted = set(suite.checks)
        return {n: s for n, s in self.checks.items() if n in wanted or s.get("group") in wanted}

    def suite(self, name: str) -> Suite:
        """Return a suite by name; raises ConfigError listing the ones that exist."""
        if name not in self.suites:
            raise ConfigError(f"Agent '{self.name}' has no suite '{name}'. Suites: {sorted(self.suites)}")
        return self.suites[name]


def list_agents() -> list[str]:
    """Return every agent folder with an agent.yaml, plus sub-parts like 'knowledge_agent/pipeline'.
    Folders starting with _ (the template) are skipped."""
    agents = [p for p in paths.AGENTS_DIR.iterdir() if (p / "agent.yaml").is_file() and not p.name.startswith("_")]
    nested = [f"{p.name}/{sub.name}" for p in agents for sub in p.iterdir() if (sub / "agent.yaml").is_file()]
    return sorted([p.name for p in agents] + nested)


def load_agent(name: str) -> Agent:
    """Read and validate agents/<name>/agent.yaml and return an Agent.
    Raises ConfigError on any mistake, before anything runs."""
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
            # Rubric paths are relative to the agent folder.
            rubric = folder / spec["rubric"]
            if not rubric.is_file():
                raise ConfigError(f"{path}: rubric for '{metric_name}' not found: {rubric}")
            spec["rubric"] = str(rubric)
        json_path = (spec.get("options") or {}).get("json_path")
        if json_path:                      # Pegasus criteria file, relative to the agent folder
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
            targets=_targets(spec.get("targets"), f"{path}: suite '{suite_name}'"),
            traces=str(spec.get("traces") or suite_name),
        )

    fields_file = folder / "fields.yaml"
    fields = {}
    if fields_file.is_file():
        fields = extract.validate((yaml.safe_load(fields_file.read_text()) or {}).get("fields") or {},
                                  str(fields_file), folder)

    checks = _load_checks(raw, folder)
    known = {*checks, *(s.get("group") for s in checks.values() if s.get("group")), *BASIC_CHECKS}
    for suite in suites.values():
        unknown = sorted(set(suite.checks or []) - known)
        if unknown:
            raise ConfigError(f"{path}: suite '{suite.name}' checks: {unknown} are neither checks nor groups. "
                              f"Known: {sorted(known)}")
        allowed = {*suite.metrics, *checks, "answer_non_empty", *SPECIAL_TARGETS}
        unknown = sorted(set(suite.targets) - allowed)
        if unknown:
            raise ConfigError(f"{path}: suite '{suite.name}' targets: {unknown} are not judges of this suite, "
                              f"checks, or one of {list(SPECIAL_TARGETS)}")
    consistency = _consistency(raw.get("consistency"), str(path))

    return Agent(
        name=name,
        folder=folder,
        connection=raw["connection"],
        input_field=raw.get("input_field", "question"),
        message_template=raw.get("message_template"),
        message_fields=_message_fields(raw.get("message"), str(path)),
        consistency=consistency,
        review_sheet=_review_sheet(raw, folder, fields),
        metrics=metrics,
        suites=suites,
        fields=fields,
        checks=checks,
    )


def _load_checks(raw: dict, folder: Path) -> dict[str, dict[str, Any]]:
    """Return the agent's deterministic checks from its optional checks.yaml.
    Raises ConfigError if agent.yaml has a top-level `checks:` section (it belongs in checks.yaml)."""
    if raw.get("checks"):
        raise ConfigError(f"{folder / 'agent.yaml'}: the `checks:` section belongs in {folder / 'checks.yaml'} "
                          f"(move it there unchanged; suites keep their `checks:` selection in agent.yaml)")
    file = folder / "checks.yaml"
    if not file.is_file():
        return {}
    return yaml_checks.validate(env.expand(yaml.safe_load(file.read_text()) or {}).get("checks") or {}, str(file))


# Checks every agent gets, selectable by name or as the group "basic".
BASIC_CHECKS = ("basic", "answer_non_empty", "keywords")


# Targets that aren't a judge or check pass rate.
SPECIAL_TARGETS = ("error_rate", "case_pass_rate", "consistency")


def _targets(spec: Any, where: str) -> dict[str, float]:
    """Validate a suite's `targets:` map of names to numbers between 0 and 1."""
    if not spec:
        return {}
    if not isinstance(spec, dict) or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in spec.values()):
        raise ConfigError(f"{where}: targets: must map names to numbers between 0 and 1, e.g. {{correctness: 0.9}}")
    return {str(k): float(v) for k, v in spec.items()}


# The SME review sheet (make review-sheet): its own file, and what a column value can be.
REVIEW_SHEET = "exporters/review_sheet.yaml"
CASE_VALUES = ("case.question", "case.answer", "case.expected_answer")
COLOURS = ("green", "red")


def _review_sheet(raw: dict, folder: Path, fields: dict[str, Any]) -> dict[str, dict]:
    """Return the review sheet's columns from the optional exporters/review_sheet.yaml as
    {group: {heading: value}}; {} when there is no file (the sheet then shows the basic columns)."""
    if raw.get("review_columns"):
        raise ConfigError(f"{folder / 'agent.yaml'}: `review_columns:` moved to {folder / REVIEW_SHEET} "
                          f"(under `columns:`, grouped by band; see the knowledge_agent one)")
    file = folder / REVIEW_SHEET
    if not file.is_file():
        return {}
    columns = (yaml.safe_load(file.read_text()) or {}).get("columns") or {}
    if not isinstance(columns, dict) or not all(isinstance(c, dict) for c in columns.values()):
        raise ConfigError(f"{file}: columns: must be {{group: {{column heading: value}}}}")
    for group, headings in columns.items():
        for heading, value in headings.items():
            _check_review_value(value, fields, f"{file}: '{group}' > '{heading}'")
    return columns


def _check_review_value(value: Any, fields: dict[str, Any], where: str) -> None:
    """Raise ConfigError unless `value` is a case value, input.<key>, a field, a list of those,
    or {value: .., colours: {text: green | red}}."""
    if isinstance(value, dict):
        unknown = set(value) - {"value", "colours"}
        colours = value.get("colours") or {}
        if unknown or "value" not in value or not isinstance(colours, dict):
            raise ConfigError(f"{where}: use {{value: <field>, colours: {{HIGH: green, LOW: red}}}}")
        bad = sorted({str(c) for c in colours.values()} - set(COLOURS))
        if bad:
            raise ConfigError(f"{where}: colours can be {list(COLOURS)} (got {bad})")
        _check_review_value(value["value"], fields, where)
        return
    for source in value if isinstance(value, list) else [value]:
        source = str(source)
        if source.startswith("case.") and source not in CASE_VALUES:
            raise ConfigError(f"{where}: '{source}' isn't one of {list(CASE_VALUES)}")
        if not source.startswith(("case.", "input.")) and source not in fields:
            raise ConfigError(f"{where}: '{source}' is not a field in fields.yaml (or case.* / input.*)")


def _consistency(spec: Any, where: str) -> dict[str, Any]:
    """Validate `consistency:` (same, min_overlap, all_pass, report): what "the same" means for REPS > 1."""
    if not spec:
        return {}
    unknown = set(spec) - {"same", "min_overlap", "all_pass", "report"} if isinstance(spec, dict) else set()
    if not isinstance(spec, dict) or unknown:
        raise ConfigError(f"{where}: consistency: allows same, min_overlap, all_pass, report (got {sorted(unknown)})")
    return {"same": spec.get("same"), "min_overlap": float(spec.get("min_overlap", 1.0)),
            "all_pass": list(spec.get("all_pass") or []), "report": list(spec.get("report") or [])}


def _message_fields(spec: Any, where: str) -> dict[str, str]:
    """Return `message: {format: json, fields: {agent_key: input_key}}` as {agent_key: input_key}.
    The runner then sends the input as a JSON object inside the message text."""
    if not spec:
        return {}
    if not isinstance(spec, dict) or spec.get("format") != "json" or not isinstance(spec.get("fields"), dict):
        raise ConfigError(f"{where}: message: must be {{format: json, fields: {{agent_key: input_key}}}}")
    return {str(k): str(v) for k, v in spec["fields"].items()}


def _suite_checks(value: Any, where: str) -> list[str] | None:
    """Turn a suite's `checks:` into None (all), [] (none) or the listed names."""
    if value in ("all", None):
        return None
    if value in ("none", [], False):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: checks: must be all, none, or a list of check / group names")
    return list(value)
