"""
Write a formatted Excel (.xlsx) file: one or more sheets, each a table with borders, a coloured header,
wrapped text, sensible column widths, frozen headers and a filter on every column.

    write_xlsx("cases.xlsx", [Sheet("golden", columns=[("Input", "Question"), ("Expected", "Expected answer")],
                                    rows=[["How do I ...?", "Open MCP ..."]])])

A column is (group, header). When columns have groups, a band row above the headers names each group
("Input", "Expected", ...) in its own colour. Values: text, numbers, True/False; None -> empty cell.
Cell(value, "good" | "bad" | "input") colours one cell: green, red, or yellow (a cell for someone to fill).
Sheet(..., dropdowns={column: ["pass", "fail"]}) gives a column a drop-down list of allowed values.

Like the reader (src/importers/spreadsheet.py) this needs no extra package: an .xlsx is a zip of XML
files, written here with the standard library.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

MAX_CELL_TEXT = 32_000            # Excel's limit is 32,767 characters per cell
MIN_WIDTH, MAX_WIDTH = 10, 60     # column widths, in characters
MAX_LINES = 12                    # tallest row, in lines of text (the cell scrolls beyond that)

# Band colours per group (anything else: grey). Header: dark blue with white text.
GROUP_STYLES = {"Input": 2, "Expected": 3, "Metadata": 4}
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="5">
  <font><sz val="11"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FF1F3864"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FF006100"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FF9C0006"/><name val="Calibri"/></font>
</fonts>
<fills count="10">
  <fill><patternFill patternType="none"/></fill>
  <fill><patternFill patternType="gray125"/></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFE2EFDA"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFEDEDED"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFF7F9FC"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/></patternFill></fill>
</fills>
<borders count="2">
  <border><left/><right/><top/><bottom/><diagonal/></border>
  <border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right>
    <top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom>
    <diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  <xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  <xf numFmtId="0" fontId="2" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/></xf>
  <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/></xf>
  <xf numFmtId="0" fontId="3" fillId="8" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
  <xf numFmtId="0" fontId="4" fillId="9" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"
      applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
  <xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
HEADER, BAND_OTHER, BODY, BODY_STRIPE = 1, 5, 6, 7
TONES = {"good": 8, "bad": 9, "input": 10}


@dataclass
class Cell:
    """A value with a colour: tone "good" (green), "bad" (red) or "input" (yellow: for someone to fill)."""

    value: Any
    tone: str = ""


@dataclass
class Sheet:
    """One sheet: columns as (group, header) and the rows below them (one value per column)."""

    name: str
    columns: list[tuple[str, str]]
    rows: list[list[Any]] = field(default_factory=list)
    freeze_columns: int = 1          # columns kept visible when scrolling right (e.g. the test case id)
    dropdowns: dict[int, list[str]] = field(default_factory=dict)   # column number (1 = A) -> allowed values


def write_xlsx(path: str | Path, sheets: list[Sheet]) -> Path:
    """Write the sheets to `path` (.xlsx) and return it."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    names = _sheet_names([s.name for s in sheets])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", _content_types(len(sheets)))
        xlsx.writestr("_rels/.rels", _RELS)
        xlsx.writestr("xl/workbook.xml", _workbook(names, sheets))
        xlsx.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        xlsx.writestr("xl/styles.xml", STYLES)
        for number, sheet in enumerate(sheets, 1):
            xlsx.writestr(f"xl/worksheets/sheet{number}.xml", _worksheet(sheet))
    return path


# --- one worksheet ------------------------------------------------------------------------------------

def _worksheet(sheet: Sheet) -> str:
    has_groups = any(group for group, _ in sheet.columns)
    header_row = 2 if has_groups else 1
    last_col = _col(len(sheet.columns))
    last_row = header_row + len(sheet.rows)
    widths = _widths(sheet)

    rows_xml = []
    if has_groups:
        cells = [_cell(f"{_col(i)}1", group, GROUP_STYLES.get(group, BAND_OTHER))
                 for i, (group, _) in enumerate(sheet.columns, 1)]
        rows_xml.append(f'<row r="1" ht="20" customHeight="1">{"".join(cells)}</row>')
    cells = [_cell(f"{_col(i)}{header_row}", header, HEADER) for i, (_, header) in enumerate(sheet.columns, 1)]
    rows_xml.append(f'<row r="{header_row}" ht="30" customHeight="1">{"".join(cells)}</row>')
    for n, values in enumerate(sheet.rows, header_row + 1):
        style = BODY_STRIPE if (n - header_row) % 2 == 0 else BODY
        cells = [_cell(f"{_col(i)}{n}", value, style) for i, value in enumerate(values, 1)]
        rows_xml.append(f'<row r="{n}" ht="{_height(values, widths)}" customHeight="1">{"".join(cells)}</row>')

    frozen = _col(sheet.freeze_columns + 1) + str(header_row + 1)
    pane = (f'<pane xSplit="{sheet.freeze_columns}" ySplit="{header_row}" topLeftCell="{frozen}" '
            f'activePane="bottomRight" state="frozen"/>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    merges = _group_merges(sheet.columns) if has_groups else []
    merge_xml = (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges)
                 + "</mergeCells>") if merges else ""
    lists = "".join(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
                    f'sqref="{_col(c)}{header_row + 1}:{_col(c)}{max(last_row, header_row + 1)}">'
                    f'<formula1>"{escape(",".join(values))}"</formula1></dataValidation>'
                    for c, values in sheet.dropdowns.items())
    if lists:
        merge_xml += f'<dataValidations count="{len(sheet.dropdowns)}">{lists}</dataValidations>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{last_col}{last_row}"/>'
            f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
            f'<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols>'
            f'<sheetData>{"".join(rows_xml)}</sheetData>'
            f'<autoFilter ref="A{header_row}:{last_col}{last_row}"/>{merge_xml}'
            '<pageMargins left="0.5" right="0.5" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
            '</worksheet>')


def _cell(ref: str, value: Any, style: int) -> str:
    """One cell: a number stays a number; everything else is text. A Cell brings its own colour."""
    if isinstance(value, Cell):
        value, style = value.value, TONES.get(value.tone, style)
    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    text = _xml_text(str(value))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _xml_text(text: str) -> str:
    """Text safe for the XML: no control characters, cut at Excel's limit, & < > escaped."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if len(text) > MAX_CELL_TEXT:
        text = text[:MAX_CELL_TEXT] + " … [cut]"
    return escape(text)


def _widths(sheet: Sheet) -> list[float]:
    """Each column as wide as its longest line (header included), within MIN_WIDTH..MAX_WIDTH."""
    widths = []
    for i, (_, header) in enumerate(sheet.columns):
        texts = [_text(row[i]) for row in sheet.rows if i < len(row)]
        longest = max([len(line) for text in texts for line in text.splitlines()] + [len(header)])
        widths.append(min(MAX_WIDTH, max(MIN_WIDTH, longest + 2)))
    return widths


def _text(value: Any) -> str:
    value = value.value if isinstance(value, Cell) else value
    return str(value if value is not None else "")


def _height(values: list[Any], widths: list[float]) -> int:
    """Row height (points) to show the tallest wrapped cell, up to MAX_LINES lines."""
    lines = 1
    for value, width in zip(values, widths, strict=False):
        value = value.value if isinstance(value, Cell) else value
        text = str(value if value is not None else "")
        wrapped = sum(max(1, -(-len(line) // int(width - 1))) for line in text.splitlines() or [""])
        lines = max(lines, wrapped)
    return 15 * min(lines, MAX_LINES) + 3


def _group_merges(columns: list[tuple[str, str]]) -> list[str]:
    """Cell ranges in the band row to merge: each run of columns in the same group."""
    merges, start = [], 1
    for i in range(2, len(columns) + 2):
        if i > len(columns) or columns[i - 1][0] != columns[start - 1][0]:
            if i - 1 > start and columns[start - 1][0]:          # a named group over 2+ columns
                merges.append(f"{_col(start)}1:{_col(i - 1)}1")
            start = i
    return merges


def _col(number: int) -> str:
    """Column letter(s): 1 -> A, 27 -> AA."""
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


# --- the workbook around the sheets -------------------------------------------------------------------

def _sheet_names(names: list[str]) -> list[str]:
    """Valid, unique sheet names: no []:*?/\\ and at most 31 characters."""
    taken, result = set(), []
    for name in names:
        clean = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "Sheet"
        candidate, n = clean, 2
        while candidate.lower() in taken:
            candidate, n = f"{clean[:28]}_{n}", n + 1
        taken.add(candidate.lower())
        result.append(candidate)
    return result


def _workbook(names: list[str], sheets: list[Sheet]) -> str:
    sheet_xml = "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                        for i, n in enumerate(names, 1))
    filters = ""
    for i, (name, sheet) in enumerate(zip(names, sheets, strict=True)):
        header_row = 2 if any(g for g, _ in sheet.columns) else 1
        ref = f"'{name}'!$A${header_row}:${_col(len(sheet.columns))}${header_row + len(sheet.rows)}"
        filters += (f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                    f'{escape(ref)}</definedName>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{sheet_xml}</sheets><definedNames>{filters}</definedNames></workbook>')


def _workbook_rels(count: int) -> str:
    rels = "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="http://schemas.openxmlformats'
                   f'.org/officeDocument/2006/relationships/worksheet"/>' for i in range(1, count + 1))
    rels += (f'<Relationship Id="rId{count + 1}" Target="styles.xml" Type="http://schemas.openxmlformats.org/'
             'officeDocument/2006/relationships/styles"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')


def _content_types(count: int) -> str:
    sheets = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                     'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, count + 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            f'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{sheets}</Types>')


_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Target="xl/workbook.xml" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/officeDocument"/></Relationships>')
