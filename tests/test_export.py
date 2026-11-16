"""make export-cases: test case JSON files -> one formatted Excel workbook (read back with our own reader)."""

import zipfile

import pytest

from src.core.exceptions import ConfigError
from src.exporters.cases import export_cases
from src.exporters.xlsx import Sheet, _col, write_xlsx
from src.importers.spreadsheet import read_rows


def test_every_suite_becomes_a_sheet_with_a_row_per_case(tmp_path, capsys):
    out = export_cases("knowledge_agent", out=tmp_path / "cases.xlsx")
    assert "test case(s) from" in capsys.readouterr().out
    summary = {r["Suite"]: r["Cases"] for r in read_rows(out, sheet="Summary")}
    assert summary["sanity"] == 2 and summary["negative"] == 12              # decline/ (8) + errors/ (4)
    sanity = read_rows(out, sheet="sanity", header_row=2)                  # row 1: the Input / Expected band
    assert [r["Test case ID"] for r in sanity] == ["TC_002", "TC_012"]
    assert sanity[0]["Question"] == "How do I add a support need?" and sanity[0]["File"] == "TC_002.json"
    assert sanity[1]["Expected answer"].startswith("Always balance data privacy")   # long text, line breaks kept
    negative = read_rows(out, sheet="negative", header_row=2)
    assert len(negative) == 12 and "TRUE" in [r.get("Should decline") for r in negative]
    sheets = zipfile.ZipFile(out).read("xl/workbook.xml").decode()
    assert "coverage" in sheets and "diagnose" not in sheets               # golden folder not imported here


def test_one_suite_only(tmp_path, monkeypatch):
    out = export_cases("knowledge_agent", "negative", tmp_path / "negative.xlsx")
    assert len(read_rows(out, sheet="negative", header_row=2)) == 12

    from src.core.agent_config import load_agent
    def with_empty_golden(name):
        agent = load_agent(name)
        agent.suite("golden").testdata = tmp_path / "not_imported_yet"
        return agent
    monkeypatch.setattr("src.exporters.cases.load_agent", with_empty_golden)
    with pytest.raises(ConfigError, match="no test cases to export in suite golden"):
        export_cases("knowledge_agent", "golden", tmp_path / "none.xlsx")


def test_the_workbook_writer(tmp_path):
    lists_and_marks = Sheet("odd: name/with*chars", [("Input", "Question"), ("Expected", "Pages")],
                            [["A & B < C", "1\n2"], [None, 3]])
    out = write_xlsx(tmp_path / "w.xlsx", [lists_and_marks])
    rows = read_rows(out, sheet="odd_ name_with_chars", header_row=2)       # sheet name made valid
    assert rows == [{"_row": 3, "Question": "A & B < C", "Pages": "1\n2"}, {"_row": 4, "Question": "", "Pages": 3}]
    assert (_col(1), _col(26), _col(27)) == ("A", "Z", "AA")
