"""Spreadsheet importer: .xlsx/.csv reading, the Knowledge Agent CJM golden mapping, and its checks."""

import json
import zipfile
from xml.sax.saxutils import escape

import pytest

from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.importers.cases import import_cases
from src.importers.spreadsheet import read_rows, sheet_names
from src.runners.test_cases import load_cases

HEADERS = ["Test ID", "Workstream", "Query Type", "User Query", "Question Type", "Expected Golden Answer",
           "Expected - Anchor Page", "Expected Relational Page", "Page Ids"]

# Rows shaped like the CJM golden sheet (cut down).
ROWS = [
    [28, "Brand Change", "Simple", "What are the benefits of the Halifax brand change?", "Why",
     "Customers will benefit from access to a broader range of products.",
     "Brand Transformation - Changing Our Brand", "NA", 43428],
    [30, "CVH", "Simple", "Hows does a customer remove consent for a support need?", "How",
     "Check which support needs they want removed.", "How Customers Can Withdraw Consent", "", ""],
    [36, "CVH", "Simple", "Do I need to follow the TEXAS model when I record a support need received in writing?",
     "Yes/No", "", "Recording a Clear Support Need in Written Communication", "", ""],
    [44, "CVH", "Complex", "I have a 14 year old customer who manages their account. Can I add a support need?",
     "How", "Adding a Support Need for Customers Under 16\n13 to 16-year-olds can give consent.",
     "Consent Needed for Support Needs\nHow to Add a support need in MCP", "", "40015\n40345"],
    [45, "Black horse", "Simple", "", "How", "", "", "", ""],          # no question: skipped
]


def write_xlsx(path, sheets):
    """A minimal real .xlsx: {sheet name: [header row, data rows...]}. Text goes in sharedStrings."""
    shared: list[str] = []

    def cell(ref, value):
        if value == "":
            return ""
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        shared.append(str(value))
        return f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'

    sheet_xml = []
    for rows in sheets.values():
        body = "".join(
            f'<row r="{r}">' + "".join(cell(f"{chr(65 + c)}{r}", v) for c, v in enumerate(row)) + "</row>"
            for r, row in enumerate(rows, start=1))
        sheet_xml.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         f"<sheetData>{body}</sheetData></worksheet>")
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    workbook = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                f'xmlns:r="{ns_r}"><sheets>' + "".join(
                    f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                    for i, name in enumerate(sheets, start=1)) + "</sheets></workbook>")
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        f'<Relationship Id="rId{i}" Type="{ns_r}/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)) + "</Relationships>")
    strings = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
               "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", rels)
        book.writestr("xl/sharedStrings.xml", strings)
        for i, xml in enumerate(sheet_xml, start=1):
            book.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return path


@pytest.fixture
def golden_xlsx(tmp_path):
    return write_xlsx(tmp_path / "KA golden.xlsx", {"Sheet1": [HEADERS, *ROWS], "Misaligned Anchor Pages": [["x"]]})


def test_xlsx_rows_keep_line_breaks_and_whole_numbers(golden_xlsx):
    assert sheet_names(golden_xlsx) == ["Sheet1", "Misaligned Anchor Pages"]
    rows = read_rows(golden_xlsx, sheet="sheet1")
    assert rows[0]["_row"] == 2 and rows[0]["Test ID"] == 28 and rows[0]["Page Ids"] == 43428
    assert rows[3]["Expected - Anchor Page"] == "Consent Needed for Support Needs\nHow to Add a support need in MCP"
    with pytest.raises(ConfigError, match="no sheet 'Nope'"):
        read_rows(golden_xlsx, sheet="Nope")


def test_cjm_golden_import(ka_copy, golden_xlsx):
    summary = import_cases("knowledge_agent", str(golden_xlsx))
    assert summary["written"] == {"new": 4, "updated": 0, "unchanged": 0}
    assert summary["skipped"] == ["row 6: no question"]

    case = json.loads((ka_copy / "testdata/golden/cvh/KA_GLD_CVH_044.json").read_text())
    assert case["test_case_id"] == "KA_GLD_CVH_044"
    assert case["input"] == {"question": ROWS[3][3], "question_type": "how"}       # question_type is sent
    assert case["expected"]["expected_anchor_page_titles"] == ["Consent Needed for Support Needs",
                                                               "How to Add a support need in MCP"]
    assert case["expected"]["expected_anchor_page_ids"] == ["40015", "40345"]      # page ids are text
    assert case["metadata"]["domain"] == "CVH" and case["expected"]["expected_query_type"] == "complex"
    assert case["metadata"]["source"] == {"file": "KA golden.xlsx", "sheet": "Sheet1", "row": 5, "test_id": 44}

    brand = json.loads((ka_copy / "testdata/golden/brand_change/KA_GLD_BRAND_CHANGE_028.json").read_text())
    assert "expected_related_page_titles" not in brand["expected"]                  # NA -> left out
    assert brand["expected"]["expected_anchor_page_ids"] == ["43428"]
    texas = json.loads((ka_copy / "testdata/golden/cvh/KA_GLD_CVH_036.json").read_text())
    assert "expected_answer" not in texas["expected"]                               # correctness will SKIP
    assert texas["input"]["question_type"] == "yes_no"
    assert summary["empty"] == {"no expected_answer: correctness judge will be skipped": ["KA_GLD_CVH_036"]}

    agent = load_agent("knowledge_agent")                                           # the runner can load them
    assert len(load_cases(agent, agent.suite("golden"))) == 4


def test_reimport_is_idempotent_and_reports_stale_files(ka_copy, golden_xlsx):
    import_cases("knowledge_agent", str(golden_xlsx))
    (ka_copy / "testdata/golden/cvh/KA_GLD_CVH_999.json").write_text("{}")
    summary = import_cases("knowledge_agent", str(golden_xlsx))
    assert summary["written"] == {"new": 0, "updated": 0, "unchanged": 4}
    assert summary["stale"] == ["testdata/golden/cvh/KA_GLD_CVH_999.json"]           # listed, not deleted


def test_dry_run_writes_nothing(ka_copy, golden_xlsx):
    summary = import_cases("knowledge_agent", str(golden_xlsx), dry_run=True)
    assert summary["written"]["new"] == 4
    assert not (ka_copy / "testdata/golden").exists()


def test_problems_stop_the_import_with_a_clear_message(ka_copy, tmp_path):
    renamed = write_xlsx(tmp_path / "a.xlsx", {"Sheet1": [["Test ID", "Question"], [1, "q"]]})
    with pytest.raises(ConfigError, match=r"columns not found: .*User Query"):
        import_cases("knowledge_agent", str(renamed))

    dupes = write_xlsx(tmp_path / "b.xlsx", {"Sheet1": [HEADERS, ROWS[1], ROWS[1]]})
    with pytest.raises(ConfigError, match="Duplicate test case ids.*Nothing written"):
        import_cases("knowledge_agent", str(dupes))
    assert not (ka_copy / "testdata/golden").exists()


def test_csv_and_unknown_domains(ka_copy, tmp_path):
    csv_file = tmp_path / "golden.csv"
    csv_file.write_text(",".join(HEADERS) + "\n7,PCA,Simple,What is PCA?,What,An answer.,Some Page,,\n")
    summary = import_cases("knowledge_agent", str(csv_file))
    assert (ka_copy / "testdata/golden/pca/KA_GLD_PCA_007.json").is_file()
    assert any("domain 'PCA' not in domain.codes" in w for w in summary["warnings"])
