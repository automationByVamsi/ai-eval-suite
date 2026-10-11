"""
`make export-cases`: every test case JSON file of an agent -> one Excel workbook, to attach or review.
The reverse of `make import-cases`.

    make export-cases AGENT=knowledge_agent                   # every suite, one sheet each
    make export-cases AGENT=knowledge_agent SUITE=golden      # one suite
    make export-cases AGENT=knowledge_agent FILE=~/Desktop/KA_cases.xlsx

The first sheet is a summary (suite, folder, number of cases); then one sheet per suite, one row per
test case. Columns: Test case ID, Description, then every key of the cases' input, expected and
metadata blocks (a coloured band above the headers says which block), then the file it came from.
A list becomes one item per line in its cell. Suites that share a folder (e.g. sanity and
relevance_only) are exported once. Generic: works for any agent.
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
    """Write the workbook and return its path. Prints what went where."""
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
    """One sheet: a row per case, a column per key (in the order they first appear)."""
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
    """{test case id: its file, relative to the test data folder}."""
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
    block, _, key = path.partition(".")
    return (case.get(block) or {}).get(key) if key else case.get(path)


def _cell(value: Any) -> Any:
    """A JSON value as a cell: list -> one item per line; object -> compact JSON; True -> TRUE."""
    if isinstance(value, list):
        return "\n".join(str(_cell(v)) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def _label(key: str) -> str:
    """'expected_anchor_page_ids' -> 'Expected anchor page ids'."""
    return key.replace("_", " ").strip().capitalize()


def _relative(folder: Path) -> str:
    try:
        return folder.relative_to(paths.ROOT).as_posix()
    except ValueError:
        return str(folder)
