"""
`make dashboard` opens without errors, on every kind of page: no runs yet, an ordinary run, a baseline run
and a verdict (both builds side by side). Streamlit's AppTest runs dashboard.py with no browser; every tab
and expander is drawn, so a broken import or a renamed function in any dashboard file fails here.
"""

from conftest import ROOT
from streamlit.testing.v1 import AppTest

from src.core import results
from src.runners.suite_runner import run_suite
from src.verdict.baseline import save_baseline
from src.verdict.compare import compare, save_verdict

APP = str(ROOT / "src" / "reporting" / "dashboard.py")


def open_dashboard() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def page_text(app: AppTest) -> str:
    return " ".join(str(m.value) for m in app.markdown)


def test_no_runs_yet_says_what_to_do(outputs):
    app = open_dashboard()
    assert "No runs yet" in page_text(app)


def test_run_baseline_and_verdict_pages_open(outputs):
    stable = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.4.0")
    save_baseline(stable)
    new = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.5.0")
    new.cases[0].results[0].status = results.FAIL                  # one regression to show
    passed, rows, baseline = compare(new)
    save_verdict(new, passed, rows, baseline, targets_met=True)

    app = open_dashboard()                                         # newest run first: the verdict
    text = page_text(app)
    assert "Release verdict" in text and "FAIL" in text and "1.4.0" in text
    labels = {t.label for t in app.tabs}                            # every tab on the page, nested ones too
    assert {":material/insights: Summary", ":material/compare_arrows: Comparison (2)",
            ":material/new_releases: This build · 1.5.0 (2)", ":material/history: Baseline build · 1.4.0 (2)"} <= labels

    run_menu = app.sidebar.selectbox[2]
    assert any("VERDICT FAIL · 1.5.0 vs 1.4.0" in label for label in run_menu.options)   # the sidebar label
    run_menu.set_value(stable.run_id).run()                        # the baseline run: the ordinary page
    assert not app.exception, [e.value for e in app.exception]
    assert any("Overview" in t.label for t in app.tabs) and any("Baseline" in t.label for t in app.tabs)
