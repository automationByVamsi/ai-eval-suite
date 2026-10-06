"""
`make fields`: show what every field in fields.yaml gives for saved traces — and what the
checks in checks.yaml make of them — without calling the agent or any judge.

    make fields AGENT=knowledge_agent CASE=TC_002                 one saved trace of the sanity suite
    make fields AGENT=knowledge_agent SUITE=golden                every saved trace of a suite
    make fields AGENT=knowledge_agent TRACE=path/to/trace.json    any trace file

Use it after writing a field, and whenever the agent's trace format changes:
  NOT FOUND  the path found nothing in this trace (out of date, or the agent didn't log it)
  empty      found, but empty (e.g. caveats: [])
  MISSING    a required field found nothing: runs would ERROR on this trace
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core import paths
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.fields.checks import run_checks
from src.fields.extract import extract, is_empty
from src.runners.test_cases import load_cases

WIDTH = 100


def preview(agent_name: str, suite_name: str = "sanity", case_ids: list[str] | None = None,
            trace_file: str | None = None) -> int:
    """Print fields (and checks) per trace. Returns 1 if a required field is missing, else 0."""
    agent = load_agent(agent_name)
    if not agent.fields:
        raise ConfigError(f"agents/{agent_name}/fields.yaml has no fields yet — see agents/_template/fields.yaml")
    traces = [(Path(trace_file).expanduser(), None)] if trace_file else _saved_traces(agent, suite_name, case_ids)
    problems = sum(_show(agent, path, case) for path, case in traces)
    print()
    return 1 if problems else 0


def _saved_traces(agent: Any, suite_name: str, case_ids: list[str] | None) -> list[tuple[Path, dict | None]]:
    """(trace file, its test case or None) for the suite's saved traces, or just the CASE= ones."""
    folder = paths.OUTPUTS_DIR / "traces" / agent.name / suite_name
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if case_ids:
        files = [f for f in files if f.stem in case_ids]
        unknown = sorted(set(case_ids) - {f.stem for f in files})
        if unknown:
            raise ConfigError(f"No saved trace for {unknown} in {folder} — run the case once "
                              f"(make run AGENT={agent.name} SUITE={suite_name} CASE=...)")
    if not files:
        raise ConfigError(f"No saved traces in {folder} — run the suite once, or give TRACE=<file>")
    cases = _cases_by_id(agent, suite_name)
    return [(f, cases.get(f.stem)) for f in files]


def _show(agent: Any, path: Path, case: dict | None) -> bool:
    """Print one trace's fields (and checks, when its test case is known). True if a required field is missing."""
    values, missing = extract(json.loads(path.read_text()), agent.fields, offline=True, local=True)  # saved copies
    fetch_errors = values.pop("_fetch_errors", [])
    print(f"\n=== {path.name}" + ("" if case else "   (no test case found: checks not shown)"))
    for name, value in values.items():
        print(f"  {_mark(name, value, missing):<9} {name:<26} {_short(value)}")
    for problem in fetch_errors:
        print(f"  NOTE      {problem}")
    if case and agent.checks:
        fields = {"question": case["input"].get(agent.input_field, ""), **values}
        print("  --- checks (checks.yaml) ---")
        for result in run_checks(agent.checks, fields, case):
            score = f" score={result.score:.2f}" if result.score is not None else ""
            print(f"  {result.status.upper():<9} {result.name:<26}{score} {result.reason}")
    return bool(missing)


def _mark(name: str, value: Any, missing: list[str]) -> str:
    if name in missing:
        return "MISSING"
    if value is None:
        return "NOT FOUND"
    return "empty" if is_empty(value) else ""


def _cases_by_id(agent: Any, suite_name: str) -> dict[str, dict[str, Any]]:
    try:
        return {c["test_case_id"]: c for c in load_cases(agent, agent.suite(suite_name))}
    except ConfigError:
        return {}


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", "\\n")
    return text if len(text) <= WIDTH else text[: WIDTH - 3] + "..."
