"""
`make export-cases`: write an agent's test cases to one Excel workbook (the reverse of `make import-cases`).
A summary sheet, then one sheet per suite with a row per case; suites sharing a folder are exported once.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core import paths
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.exporters.xlsx import Sheet, write_xlsx
from src.runners.test_cases import load_cases

BLOCKS = {"input": "Input", "expected": "Expected", "metadata": "Metadata"}
FIRST = ["test_case_id", "description"]
LABELS = {"test_case_id": "Test case ID", "description": "Description"}


def export_cases(agent_name: str, suite: str | None = None, out: str | Path | None = None) -> Path:
    """Write the workbook, print what went where, and return its path."""
    agent = load_agent(agent_name)
    suites = [agent.suite(suite)] if suite else list(agent.suites.values())
    sheets, summary, seen = [], [], set()
    for s in suites:
        key = (s.testdata, json.dumps(s.only, sort_keys=True))
        if key in seen:                                   # same cases as a suite already exported
            continue
        seen.add(key)
        try:
            cases = load_cases(agent, s)
        except ConfigError:                               # no folder / no cases yet: noted, not fatal
            summary.append([s.name, _relative(s.testdata), 0, "no test cases yet"])
            continue
        sheets.append(cases_sheet(s.name, cases, s.testdata))
        summary.append([s.name, _relative(s.testdata), len(cases), ""])
    if not sheets:
        raise ConfigError(f"{agent_name}: no test cases to export" + (f" in suite {suite}" if suite else ""))

    overview = Sheet("Summary", [("", "Suite"), ("", "Test data folder"), ("", "Cases"), ("", "Note")], summary)
    out = Path(out).expanduser() if out else (
        paths.OUTPUTS_DIR / "exports" / f"{agent.name.replace('/', '.')}_test_cases_{datetime.now():%Y%m%d_%H%M}.xlsx")
    write_xlsx(out, [overview, *sheets])
    total = sum(row[2] for row in summary)
    print(f"{total} test case(s) from {len(sheets)} suite(s) -> {out}")
    for name, folder, count, note in summary:
        print(f"  {name:<24} {count:>5}  {folder}" + (f"   ({note})" if note else ""))
    return out


def cases_sheet(name: str, cases: list[dict[str, Any]], folder: Path) -> Sheet:
    """Build one sheet with a row per case and a column per key, in first-seen order."""
    columns: list[tuple[str, str, str]] = [("", key, key) for key in FIRST]    # (group, key, where in the case)
    for block, group in BLOCKS.items():
        keys = dict.fromkeys(k for case in cases for k in (case.get(block) or {}))
        columns += [(group, k, f"{block}.{k}") for k in keys]
    others = dict.fromkeys(k for case in cases for k in case if k not in FIRST and k not in BLOCKS
                           and not k.startswith("_"))
    columns += [("Other", k, k) for k in others]

    files = _files_by_id(folder)
    rows = [[_cell(_get(case, path)) for _, _, path in columns] + [files.get(case["test_case_id"], "")]
            for case in cases]
    headers = [(group, LABELS.get(header) or _label(header)) for group, header, _ in columns]
    return Sheet(name, headers + [("", "File")], rows)


def _files_by_id(folder: Path) -> dict[str, str]:
    """Return {test case id: its file path relative to the test data folder}."""
    found = {}
    for path in sorted(folder.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        for case in (data.get("cases", [data]) if isinstance(data, dict) else []):
            found[case.get("test_case_id", path.stem)] = path.relative_to(folder).as_posix()
    return found


def _get(case: dict[str, Any], path: str) -> Any:
    """Return the value at a "block.key" or top-level path in a case."""
    block, _, key = path.partition(".")
    return (case.get(block) or {}).get(key) if key else case.get(path)


def _cell(value: Any) -> Any:
    """Convert a JSON value to a cell: list -> one item per line, object -> JSON, bool -> TRUE/FALSE."""
    if isinstance(value, list):
        return "\n".join(str(_cell(v)) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def _label(key: str) -> str:
    """Turn a key into a header, e.g. 'expected_page_ids' -> 'Expected page ids'."""
    return key.replace("_", " ").strip().capitalize()


def _relative(folder: Path) -> str:
    """Return a folder relative to the repo, for printing."""
    try:
        return folder.relative_to(paths.ROOT).as_posix()
    except ValueError:
        return str(folder)
