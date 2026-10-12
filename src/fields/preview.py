"""
`make fields`: print each field (and check result) for saved traces, without calling the agent or judges.
Marks: NOT FOUND (path found nothing), empty, MISSING (required field absent; a run would ERROR).
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

    if trace_file:
        traces = [(Path(trace_file).expanduser(), None)]
    else:
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
        traces = [(f, cases.get(f.stem)) for f in files]

    problems = 0
    for path, case in traces:
        trace = json.loads(path.read_text())
        values, missing = extract(trace, agent.fields, offline=True, local=True)   # saved lookup copies only
        fetch_errors = values.pop("_fetch_errors", [])
        problems += bool(missing)
        print(f"\n=== {path.name}" + ("" if case else "   (no test case found: checks not shown)"))
        for name, value in values.items():
            mark = ("MISSING" if name in missing else "NOT FOUND" if value is None
                    else "empty" if is_empty(value) else "")
            print(f"  {mark:<9} {name:<26} {_short(value)}")
        for problem in fetch_errors:
            print(f"  NOTE      {problem}")
        if case and agent.checks:
            fields = {"question": case["input"].get(agent.input_field, ""), **values}
            print("  --- checks (checks.yaml) ---")
            for result in run_checks(agent.checks, fields, case):
                score = f" score={result.score:.2f}" if result.score is not None else ""
                print(f"  {result.status.upper():<9} {result.name:<26}{score} {result.reason}")
    print()
    return 1 if problems else 0


def _cases_by_id(agent: Any, suite_name: str) -> dict[str, dict[str, Any]]:
    """Return the suite's test cases by id ({} if the suite can't be loaded)."""
    try:
        return {c["test_case_id"]: c for c in load_cases(agent, agent.suite(suite_name))}
    except ConfigError:
        return {}


def _short(value: Any) -> str:
    """Render a value on one line, cut to WIDTH characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", "\\n")
    return text if len(text) <= WIDTH else text[: WIDTH - 3] + "..."
