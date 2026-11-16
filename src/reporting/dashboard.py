"""Streamlit dashboard entry point (`make dashboard`): page setup, the sidebar, and which page to open.

Read-only: it reads outputs/runs/*/results.json and baselines/.
"""

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root isn't on the import path; add it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402 — must come after the sys.path line above

from src.reporting import verdict_view as vv  # noqa: E402
from src.reporting.dashboard_data import all_run_ids, load, run_label  # noqa: E402
from src.reporting.dashboard_run import show_run_page  # noqa: E402
from src.reporting.dashboard_style import apply_theme, html  # noqa: E402
from src.reporting.dashboard_verdict import show_verdict_page  # noqa: E402
from src.reporting.html_report import report_html  # noqa: E402

st.set_page_config(page_title="Agent evals", page_icon=":material/fact_check:", layout="wide")
apply_theme()

# --- no runs yet: say what to do, then stop -------------------------------------------------------

run_ids = all_run_ids()         # newest first
if not run_ids:
    html('<div class="hero"><div><div class="hero-title">No runs yet</div><div class="hero-sub">'
         'Run a suite, then refresh: <code>make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1</code>'
         '</div></div></div>')
    st.stop()

# --- sidebar: which run, which cases --------------------------------------------------------------

with st.sidebar:
    st.markdown("### :material/fact_check: Agent evals")

    # Group runs by (agent, suite) so the menus only offer choices that exist.
    by_pair: dict[tuple[str, str], list[str]] = {}
    for rid in run_ids:
        r = load(rid)
        by_pair.setdefault((r.agent, r.suite), []).append(rid)
    agents = sorted({a for a, _ in by_pair})
    agent = st.selectbox("Agent", agents, format_func=lambda a: a.replace("_", " ").title())
    suites = sorted({s for a, s in by_pair if a == agent})
    suite = st.selectbox("Suite", suites)
    run_id = st.selectbox("Run", by_pair[(agent, suite)], format_func=run_label,
                          help="Newest first. ⚖ VERDICT = a `make verdict` (opens the build comparison), "
                               "★ BASELINE = the run saved by `make baseline`.")
    st.divider()
    st.markdown("**Filter test cases**")
    status_filter = st.pills("Status", ["Fail", "Error", "Pass"], selection_mode="multi",
                             default=["Fail", "Error", "Pass"], label_visibility="collapsed")
    search = st.text_input("Search", placeholder="case id, question or answer text",
                           label_visibility="collapsed")
    st.caption("Results are read from outputs/runs. Refresh the page after a new run.")

# --- the selected run: a verdict gets the release view, anything else the ordinary run page -------

run = load(run_id)
with st.sidebar:                # the selected run as one HTML file, to share without Streamlit
    st.download_button(":material/download: Download HTML report", report_html(run),
                       file_name=f"{run.run_id}.html", mime="text/html", width="stretch",
                       help="The Overview, Test cases and Consistency views as a single file that opens "
                            "in any browser. Same as `make report`.")
verdict = vv.load(run)          # None unless the run was saved by `make verdict`
if verdict is not None:
    show_verdict_page(verdict, status_filter, search)
else:
    show_run_page(run, by_pair[(agent, suite)], status_filter, search)
