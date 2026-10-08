"""
Showing results. Everything here only READS saved runs; nothing here changes a result.

Printed in the terminal:
  console.py                 the report printed after make run / make verdict
  summary.py                 the numbers the console and the dashboard share (pass rate per judge / check)

Numbers about a run:
  release.py                 the suite's release targets, and whether repeated runs agree (consistency)
  verdict_view.py            the data behind the release view of a `make verdict` run
  calibration.py             how well the LLM judges agree with human labels

The Streamlit dashboard (make dashboard). Start at dashboard.py, which is only the entry point:
  dashboard.py               page setup, the sidebar, and which page to open
  dashboard_run.py           the page of an ordinary run (Overview, Trends, Baseline tabs)
  dashboard_consistency.py   the Consistency tab of that page (runs with REPS > 1)
  dashboard_verdict.py       the page of a `make verdict` run (PASS / FAIL, both builds side by side)
  dashboard_verdict_parts.py small charts and HTML pieces used by that page
  dashboard_cases.py         the list of test cases, used by both pages
  dashboard_data.py          reading the saved runs
  dashboard_style.py         colours and CSS
  dashboard_parts.py         helpers that build HTML text (no Streamlit, so tests can check them directly)
"""
