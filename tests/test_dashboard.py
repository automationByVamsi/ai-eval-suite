"""The results dashboard: error explanations, judges vs checks, and the app itself rendering a saved run."""

from conftest import ROOT
from streamlit.testing.v1 import AppTest

from src.core.results import CaseResult, Result
from src.reporting import dashboard_parts as ui
from src.runners.suite_runner import run_suite


def test_every_error_is_explained_with_a_fix():
    case = CaseResult("TC_1", results=[
        Result("lookup", "check", "error", "contexts: get_page_content_from_athena(40017) failed: ConnectError",
               group="setup"),
        Result("faithfulness", "judge", "error", "RateLimitError"),
    ])
    found = ui.problems(case)
    assert [p["title"] for p in found] == ["A value could not be looked up outside the trace",
                                          "The Faithfulness judge could not score this case"]
    assert "lookups.py" in found[0]["hint"] and "(40017)" in found[0]["reason"]
    assert ui.problems(CaseResult("TC_2", error="agent: ReadTimeout"))[0]["title"] == "The agent did not answer"


def test_judges_and_checks_are_kept_apart_and_setup_errors_are_neither():
    case = CaseResult("TC_1", results=[
        Result("answer_non_empty", "check", "pass", group="basic"),
        Result("anchor_hit", "check", "fail", "none of ['49999']", group="retrieval"),
        Result("lookup", "check", "error", group="setup"),
        Result("relevance", "judge", "pass", score=0.9, threshold=0.7),
    ])
    judges, groups = ui.split(case)
    assert [r.name for r in judges] == ["relevance"]
    assert {g: [r.name for r in rs] for g, rs in groups.items()} == {"basic": ["answer_non_empty"],
                                                                   "retrieval": ["anchor_hit"]}
    assert ui.first_issue(case) == "A value could not be looked up outside the trace"    # errors before fails


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


def test_banner_checks_show_red_when_they_fail_the_case_and_orange_when_diagnostic():
    from src.core.results import Result
    case = CaseResult("TC_9", results=[
        Result("within_60s", "check", "fail", "The agent took 72.4 s, over the 60 s limit",
               diagnostic=True, banner=True),
        Result("within_90s", "check", "pass", banner=True),
        Result("anchor_hit", "check", "fail", "missed", diagnostic=True)])           # no banner: not marked
    shown = ui.banners_html(case)
    assert shown.count('class="banner') == 1 and 'class="banner warn"' in shown
    assert "Within 60s" in shown and "72.4 s, over the 60 s limit" in shown and "doesn&#x27;t fail" in shown
    case.results[1] = Result("within_90s", "check", "fail", "The agent took 95.0 s, over the 90 s limit", banner=True)
    assert 'class="banner bad"' in ui.banners_html(case) and case.status == "fail"
