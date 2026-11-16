"""
Read spreadsheet rows (.xlsx or .csv) as dicts keyed by header text, plus "_row" (the sheet row number).
.xlsx is parsed with the standard library only; .xls is not supported.
"""

from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from src.core.exceptions import ConfigError

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def read_rows(path: str | Path, sheet: str | None = None, header_row: int = 1) -> list[dict[str, Any]]:
    """Return the non-empty rows under `header_row` as dicts keyed by header text, plus "_row"."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"Spreadsheet not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        grid = _xlsx_grid(path, sheet)
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:   # utf-8-sig: Excel's CSV export
            grid = {i: dict(enumerate(row)) for i, row in enumerate(csv.reader(handle), start=1)}
    else:
        raise ConfigError(f"{path.name}: only .xlsx and .csv are supported (save .xls files as .xlsx)")

    header_cells = grid.get(header_row, {})
    headers = {col: str(text).strip() for col, text in header_cells.items() if str(text).strip()}
    if not headers:
        raise ConfigError(f"{path.name}: row {header_row} has no column headers (set header_row in the mapping)")

    rows = []
    for number in sorted(n for n in grid if n > header_row):
        cells = grid[number]
        row = {header: _clean(cells.get(col, "")) for col, header in headers.items()}
        if any(value != "" for value in row.values()):
            rows.append({"_row": number, **row})
    return rows


def sheet_names(path: str | Path) -> list[str]:
    """Return the sheet names of an .xlsx file, in workbook order."""
    with zipfile.ZipFile(Path(path).expanduser()) as book:
        return [name for name, _ in _sheets(book)]


def _clean(value: Any) -> Any:
    """Trim text, normalise line breaks to \\n, and turn whole numbers like "28.0" into int."""
    if isinstance(value, str):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if re.fullmatch(r"-?\d+(\.0+)?", value):
            return int(float(value))
    return value


# --- .xlsx -------------------------------------------------------------------------------------

def _xlsx_grid(path: Path, sheet: str | None) -> dict[int, dict[int, str]]:
    """Return {row number: {column index: cell text}} for one sheet (the first if `sheet` is None)."""
    with zipfile.ZipFile(path) as book:
        sheets = _sheets(book)
        if not sheets:
            raise ConfigError(f"{path.name}: no sheets found")
        if sheet is None:
            target = sheets[0][1]
        else:
            matches = [t for name, t in sheets if name.strip().lower() == sheet.strip().lower()]
            if not matches:
                raise ConfigError(f"{path.name}: no sheet '{sheet}'. Sheets: {[name for name, _ in sheets]}")
            target = matches[0]
        shared = _shared_strings(book)
        root = ElementTree.fromstring(book.read(target))

    grid: dict[int, dict[int, str]] = {}
    for cell in root.iterfind(".//m:sheetData/m:row/m:c", _NS):
        ref = cell.get("r", "")
        match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
        if not match:
            continue
        column, row = _column_index(match.group(1)), int(match.group(2))
        grid.setdefault(row, {})[column] = _cell_text(cell, shared)
    return grid


def _sheets(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return [(sheet name, path of its XML inside the zip), ...]."""
    workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iterfind("rel:Relationship", _NS)}
    result = []
    for sheet in workbook.iterfind("m:sheets/m:sheet", _NS):
        target = targets.get(sheet.get(f"{{{_NS['r']}}}id"), "")
        target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        result.append((sheet.get("name", ""), target))
    return result


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    """Return the workbook's shared strings, which cells reference by index."""
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
    # A string may be split into formatted runs; join all its <t> parts.
    return ["".join(t.text or "" for t in item.iter(f"{{{_NS['m']}}}t")) for item in root.iterfind("m:si", _NS)]


def _cell_text(cell: ElementTree.Element, shared: list[str]) -> str:
    """Return a cell's text, resolving shared, inline and boolean values."""
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{_NS['m']}}}t"))
    value = cell.findtext("m:v", default="", namespaces=_NS)
    if kind == "s" and value:
        return shared[int(value)]
    if kind == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def _column_index(letters: str) -> int:
    """Convert column letters to a 0-based index (A -> 0, AA -> 26)."""
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1
