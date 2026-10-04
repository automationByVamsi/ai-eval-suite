"""
`make import-cases`: turn a spreadsheet of test cases into one JSON file per case.

    make import-cases AGENT=knowledge_agent FILE="~/Downloads/KA golden.xlsx"
                      [SHEET=Sheet1] [MAPPING=cjm_golden] [DRY_RUN=1]

Generic: this file knows nothing about any agent. What a spreadsheet's columns mean and what the
test case JSON looks like is set per agent, in a mapping file:

    agents/<agent>/importers/<mapping>.yaml     (see agents/knowledge_agent/importers/cjm_golden.yaml)

      sheet, header_row     where the table is
      columns               our name for a column -> its header text in the sheet
      required              rows without these are skipped (and listed)
      empty_values          cell text that means "no value", e.g. NA
      labelled              one cell holding labelled parts -> one value per label, e.g.
                              "Anchor: 26942  Relational: 8412; 7053"  ->  anchor_page_ids, related_page_ids
                            (a cell with no label at all goes to the first label)
      normalise             lower | upper | slug | code   (code: "Brand Change" -> BRAND_CHANGE)
      allowed               the only values a column may have, e.g. what the agent accepts; any other
                            value is left out (and counted in the summary). The sheet's value is kept
                            as {row.<name>_in_sheet}
      lists                 cells that hold several values: lines (one per line) | items (lines or ;) |
                            any (lines, , ; or spaces)
      strip                 a regex removed from each value (or each list item), e.g. a trailing "(27429)"
      domain                which column holds the domain, and its short code for ids and folders
      warn_if_empty         columns worth a warning when empty (e.g. no expected answer -> judge skipped)
      output                folder, id and the case template (placeholders, see below)

Placeholders in `output`:
  {row.<name>}       a column, by our name              {domain} {domain_folder}   CVH, cvh
  {source.file} {source.sheet} {source.row}             where the row came from
  {agent.name}       {id}                               the case id (from output.id)
  Format numbers like {row.test_id:03} -> 028. A placeholder that is the whole string keeps its type
  (a list stays a list). Empty values are left out of the JSON, so a missing label means the
  metric or check that needs it is SKIPPED — never guessed.

The spreadsheet is the source of truth: re-importing overwrites the JSON files it produced.
JSON files already in the output folder that no row produced are listed, never deleted.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from src.core import paths
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.importers.spreadsheet import read_rows
from src.synthesizer.output_template import render
from src.utils.text import safe_filename, slug

_ROOTS = ("row", "domain", "domain_folder", "source", "agent", "id")
_KEYS = {"sheet", "header_row", "columns", "required", "empty_values", "labelled", "normalise", "allowed", "lists",
         "strip", "domain", "warn_if_empty", "output"}


def import_cases(agent_name: str, file: str, *, mapping: str | None = None, sheet: str | None = None,
                 dry_run: bool = False) -> dict[str, Any]:
    """Read the spreadsheet, write the case files, print a summary. Returns the summary (for tests)."""
    agent = load_agent(agent_name)
    config_path = _mapping_file(agent.folder, mapping)
    config = _load_mapping(config_path)
    sheet = sheet or config.get("sheet")
    rows = read_rows(file, sheet=sheet, header_row=int(config.get("header_row", 1)))
    headers = _match_columns(config["columns"], rows, file)

    source = {"file": Path(file).expanduser().name, "sheet": sheet or "(first sheet)"}
    planned: list[tuple[Path, dict[str, Any]]] = []
    skipped: list[str] = []
    warnings: Counter[str] = Counter()
    warned_ids: dict[str, list[str]] = {}
    for raw in rows:
        values = _row_values(raw, headers, config, warnings)
        missing = [name for name in config.get("required", []) if _empty(values.get(name))]
        if missing:
            skipped.append(f"row {raw['_row']}: no {', '.join(missing)}")
            continue
        domain = _domain(values, config.get("domain") or {}, warnings)
        context = {"row": values, "domain": domain, "domain_folder": domain.lower(),
                   "source": {**source, "row": raw["_row"]}, "agent": {"name": agent.name}}
        output = config["output"]
        case_id = _render_id(output["id"], context, raw["_row"])
        case = _prune(render(output["case"], {**context, "id": case_id}, _ROOTS))
        if _empty((case.get("input") or {}).get(agent.input_field)):
            skipped.append(f"row {raw['_row']} ({case_id}): input.{agent.input_field} is empty")
            continue
        folder = agent.folder / str(render(output["folder"], context, _ROOTS))
        planned.append((folder / f"{safe_filename(case_id)}.json", case))
        for name, reason in (config.get("warn_if_empty") or {}).items():
            if _empty(values.get(name)):
                warned_ids.setdefault(f"no {name}: {reason}", []).append(case_id)

    ids = Counter(case["test_case_id"] for _, case in planned)
    duplicates = sorted(i for i, count in ids.items() if count > 1)
    if duplicates:
        raise ConfigError(f"Duplicate test case ids {duplicates} — check the id column in the sheet. Nothing written.")

    written = {"new": 0, "updated": 0, "unchanged": 0}
    for path, case in planned:
        text = json.dumps(case, indent=2, ensure_ascii=False) + "\n"
        state = "new" if not path.exists() else ("unchanged" if path.read_text() == text else "updated")
        written[state] += 1
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    root = agent.folder / _static_prefix(config["output"]["folder"])
    produced = {path.resolve() for path, _ in planned}
    stale = sorted(str(p.relative_to(agent.folder)) for p in root.rglob("*.json")
                   if p.resolve() not in produced
                   and not any(part.startswith("_") for part in p.relative_to(root).parts)) if root.is_dir() else []

    summary = {"cases": [case for _, case in planned], "paths": [p for p, _ in planned], "written": written,
               "skipped": skipped, "warnings": dict(warnings), "empty": warned_ids, "stale": stale,
               "mapping": config_path}
    _print_summary(summary, agent.name, dry_run)
    return summary


# --- mapping file ------------------------------------------------------------------------------

def _mapping_file(agent_folder: Path, name: str | None) -> Path:
    folder = agent_folder / "importers"
    available = sorted(p.stem for p in folder.glob("*.yaml")) if folder.is_dir() else []
    if name:
        path = folder / f"{name}.yaml"
        if not path.is_file():
            raise ConfigError(f"No mapping {path}. Mappings for this agent: {available or 'none'}")
        return path
    if len(available) == 1:
        return folder / f"{available[0]}.yaml"
    if not available:
        raise ConfigError(f"No importer mapping in {folder}/ — copy agents/knowledge_agent/importers/cjm_golden.yaml "
                          "there and change the columns and output template")
    raise ConfigError(f"Several mappings in {folder}/: {available}. Pick one with MAPPING=<name>")


def _load_mapping(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text()) or {}
    unknown = set(config) - _KEYS
    if unknown:
        raise ConfigError(f"{path.name}: unknown keys {sorted(unknown)} (allowed: {sorted(_KEYS)})")
    for key in ("columns", "output"):
        if not config.get(key):
            raise ConfigError(f"{path.name}: `{key}:` is required")
    for key in ("folder", "id", "case"):
        if key not in config["output"]:
            raise ConfigError(f"{path.name}: output.{key} is required")
    return config


def _match_columns(columns: dict[str, str], rows: list[dict[str, Any]], file: str) -> dict[str, str]:
    """our name -> the exact header in the sheet. Matching ignores case and extra spaces."""
    present = [h for h in (rows[0] if rows else {}) if h != "_row"]
    by_key = {_header_key(h): h for h in present}
    missing = [f"{name} ('{header}')" for name, header in columns.items() if _header_key(header) not in by_key]
    if missing:
        raise ConfigError(f"{Path(file).name}: columns not found: {missing}.\n  Headers in the sheet: {present}\n"
                          "  Fix `columns:` in the mapping (or SHEET= / header_row if this is the wrong table).")
    return {name: by_key[_header_key(header)] for name, header in columns.items()}


def _header_key(text: str) -> str:
    return " ".join(str(text).lower().split())


# --- one row -----------------------------------------------------------------------------------

def _row_values(raw: dict[str, Any], headers: dict[str, str], config: dict[str, Any],
                warnings: Counter[str] | None = None) -> dict[str, Any]:
    """Our name -> the cleaned cell value: 'no value' markers blanked, labelled parts split out, then
    normalised, then split into lists, then `strip` applied."""
    empty = {str(v).strip().lower() for v in config.get("empty_values", [])}
    values = {}
    for name, header in headers.items():
        value = raw.get(header, "")
        if isinstance(value, str) and value.strip().lower() in empty:
            value = ""
        values[name] = value

    for name, labels in (config.get("labelled") or {}).items():
        values.update(_labelled(values.get(name), labels))
    for name, how in (config.get("normalise") or {}).items():
        if not _empty(values.get(name)):
            values[name] = _normalise(str(values[name]), how)
    for name, allowed in (config.get("allowed") or {}).items():
        values[f"{name}_in_sheet"] = values.get(name, "")
        if not _empty(values.get(name)) and str(values[name]) not in {str(a) for a in allowed}:
            if warnings is not None:
                warnings[f"{name} '{values[name]}' is not one of {', '.join(map(str, allowed))}: left out"] += 1
            values[name] = ""
    for name, how in (config.get("lists") or {}).items():
        values[name] = _split(values.get(name), how, empty)
    for name, pattern in (config.get("strip") or {}).items():
        values[name] = _strip(values.get(name), pattern)
    return values


def _labelled(value: Any, labels: dict[str, str]) -> dict[str, str]:
    """
    "Anchor: 26942  Relational: 8412; 7053" with {Anchor: anchor_page_ids, Relational: related_page_ids}
    -> {"anchor_page_ids": "26942", "related_page_ids": "8412; 7053"}. Labels match case-insensitively,
    the colon is optional. A cell without any label goes to the first label (older sheets: ids only).
    """
    if not isinstance(labels, dict) or not labels:
        raise ConfigError("labelled: give each label the name its part gets, e.g. {Anchor: anchor_page_ids}")
    out = {target: "" for target in labels.values()}
    text = "" if _empty(value) else str(value)
    pattern = re.compile(r"\b(" + "|".join(re.escape(label) for label in labels) + r")\b\s*:?", re.IGNORECASE)
    marks = list(pattern.finditer(text))
    if not marks:
        out[next(iter(labels.values()))] = text.strip()
        return out
    by_lower = {label.lower(): target for label, target in labels.items()}
    for mark, following in zip(marks, [*marks[1:], None], strict=True):
        part = text[mark.end(): following.start() if following else len(text)].strip(" \t\n;,")
        target = by_lower[mark.group(1).lower()]
        out[target] = "; ".join(x for x in (out[target], part) if x)
    return out


def _strip(value: Any, pattern: str) -> Any:
    """Remove `pattern` from a value, or from each item of a list (e.g. a trailing page id in brackets)."""
    regex = re.compile(pattern)
    if isinstance(value, list):
        return [cleaned for v in value if (cleaned := regex.sub("", str(v)).strip())]
    return value if _empty(value) else regex.sub("", str(value)).strip()


def _normalise(text: str, how: str) -> str:
    if how == "lower":
        return text.strip().lower()
    if how == "upper":
        return text.strip().upper()
    if how == "slug":
        return slug(text)
    if how == "code":
        return slug(text).upper()
    raise ConfigError(f"normalise: unknown '{how}' (use lower, upper, slug or code)")


def _split(value: Any, how: str, empty: set[str]) -> list[str]:
    """A cell holding several values -> a list of strings (numbers become text: page ids are text)."""
    if _empty(value):
        return []
    if how == "lines":
        parts = str(value).split("\n")
    elif how == "items":
        parts = re.split(r"[\n;]+", str(value))
    elif how == "any":
        parts = re.split(r"[\n,;\s]+", str(value))
    else:
        raise ConfigError(f"lists: unknown '{how}' (use lines, items or any)")
    return [p.strip() for p in parts if p.strip() and p.strip().lower() not in empty]


def _domain(values: dict[str, Any], config: dict[str, Any], warnings: Counter[str]) -> str:
    """The row's short domain code, e.g. 'CVH' — from the mapping's codes, else made from the text."""
    if not config:
        return "ALL"
    text = str(values.get(config.get("column", ""), "") or "").strip()
    codes = {k.strip().lower(): v for k, v in (config.get("codes") or {}).items()}
    if not text:
        warnings["rows with no domain -> UNASSIGNED"] += 1
        return "UNASSIGNED"
    if text.lower() in codes:
        return str(codes[text.lower()])
    code = slug(text).upper()
    warnings[f"domain '{text}' not in domain.codes -> {code} (add it to the mapping to choose the code)"] += 1
    return code


def _render_id(template: str, context: dict[str, Any], row: int) -> str:
    try:
        return str(render(template, context, _ROOTS))
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"row {row}: can't build the id from '{template}': {exc} "
                          "(e.g. {row.test_id:03} needs a whole number in the id column)") from exc


def _prune(value: Any) -> Any:
    """Drop empty strings, empty lists and None, so a missing label is absent (the judge SKIPs)."""
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if not _empty(v)}
    if isinstance(value, list):
        return [v for v in (_prune(v) for v in value) if not _empty(v)]
    return value


def _relative(path: Path) -> str:
    """A path relative to the repo, for printing."""
    try:
        return str(path.relative_to(paths.ROOT))
    except ValueError:
        return str(path)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _static_prefix(folder_template: str) -> str:
    """'testdata/golden/{domain_folder}' -> 'testdata/golden' (where stale files are looked for)."""
    return folder_template.split("{", 1)[0].rstrip("/") or "."


# --- report ------------------------------------------------------------------------------------

def _print_summary(summary: dict[str, Any], agent: str, dry_run: bool) -> None:
    w = summary["written"]
    total = sum(w.values())
    verb = "Would write" if dry_run else "Wrote"
    print(f"\n{verb} {total} test case(s) for {agent}: {w['new']} new, {w['updated']} updated, "
          f"{w['unchanged']} unchanged   (mapping: {summary['mapping'].name})")
    folders = Counter(_relative(p.parent) for p in summary["paths"])
    for folder, count in sorted(folders.items()):
        print(f"  {count:>4}  {folder}")
    if summary["skipped"]:
        print(f"\nSkipped {len(summary['skipped'])} row(s):")
        for line in summary["skipped"]:
            print(f"  - {line}")
    for message, count in summary["warnings"].items():
        print(f"\nWARNING: {count} x {message}")
    for message, ids in summary["empty"].items():
        shown = ", ".join(ids[:8]) + (f" (+{len(ids) - 8} more)" if len(ids) > 8 else "")
        print(f"\nNOTE: {len(ids)} case(s) with {message}\n  {shown}")
    if summary["stale"]:
        print(f"\n{len(summary['stale'])} JSON file(s) in the output folder were not in this spreadsheet "
              "(left as they are — delete them if they are gone from the sheet):")
        for path in summary["stale"][:20]:
            print(f"  - {path}")
    if dry_run:
        print("\nDry run: nothing was written. Run again without DRY_RUN=1 to write the files.")
    print()
