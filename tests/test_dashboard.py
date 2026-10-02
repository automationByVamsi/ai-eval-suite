"""The results dashboard: error explanations, judges vs checks, and the app itself rendering a saved run."""

from conftest import ROOT
from streamlit.testing.v1 import AppTest

from src.core.results import CaseResult, Result
from src.reporting import dashboard_parts as ui
from src.runners.suite_runner import run_suite


def test_every_error_is_explained_with_a_fix():
    case = CaseResult("TC_1", results=[
        Result("evidence_fetch", "check", "error", "contexts: page 40017: ConnectError", group="setup"),
        Result("faithfulness", "judge", "error", "RateLimitError"),
    ])
    found = ui.problems(case)
    assert [p["title"] for p in found] == ["Evidence pages could not be fetched from Athena",
                                          "The Faithfulness judge could not score this case"]
    assert "HIVE_ATHENA" in found[0]["hint"] and "page 40017" in found[0]["reason"]
    assert ui.problems(CaseResult("TC_2", error="agent: ReadTimeout"))[0]["title"] == "The agent did not answer"


def test_judges_and_checks_are_kept_apart_and_setup_errors_are_neither():
    case = CaseResult("TC_1", results=[
        Result("answer_non_empty", "check", "pass", group="basic"),
        Result("anchor_hit", "check", "fail", "none of ['49999']", group="retrieval"),
        Result("evidence_fetch", "check", "error", group="setup"),
        Result("relevance", "judge", "pass", score=0.9, threshold=0.7),
    ])
    judges, groups = ui.split(case)
    assert [r.name for r in judges] == ["relevance"]
    assert {g: [r.name for r in rs] for g, rs in groups.items()} == {"basic": ["answer_non_empty"],
                                                                   "retrieval": ["anchor_hit"]}
    assert ui.first_issue(case) == "Evidence pages could not be fetched from Athena"     # errors before fails


def test_evidence_pages_carry_their_roles(outputs):
    case = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=["TC_002"]).cases[0]
    pages = {p["id"]: p for p in ui.evidence_pages(case)}
    assert pages["40345"]["title"] == "How To Add a Support Need in MCP"
    assert {"anchor", "cited"} <= set(pages["40345"]["roles"])


def test_the_app_renders_a_saved_run(outputs):
    run_suite("knowledge_agent", "sanity", offline=True, judges=False)
    app = AppTest.from_file(str(ROOT / "src/reporting/dashboard.py"), default_timeout=60).run()
    assert not app.exception, app.exception
    cases_tab = app.tabs[1]
    accordions = [b for b in cases_tab.children.values() if type(b).__name__ in ("Expander", "Status")]
    assert len(accordions) == 2                                      # one accordion per case
    labels = " ".join(a.label for a in accordions)
    assert "TC_002" in labels and "TC_012" in labels
