"""
Results dashboard: `make dashboard` (runs `streamlit run src/reporting/dashboard.py`).

Read-only: it reads outputs/runs/*/results.json and baselines/ — nothing else. Two tabs:
  Runs     pick a run, see every case, open one to see the answer, checks and judges
  Verdict  compare the run with its agent/suite baseline (same logic as `make verdict`)
"""

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root isn't on the import path; add it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402 — must come after the sys.path line above
import streamlit as st  # noqa: E402

from src.core import paths  # noqa: E402
from src.core.results import load_run  # noqa: E402
from src.verdict.baseline import baseline_path  # noqa: E402
from src.verdict.compare import compare  # noqa: E402

st.set_page_config(page_title="Agent evals", layout="wide")
st.title("Agent evaluation results")

run_ids = sorted((p.parent.name for p in (paths.OUTPUTS_DIR / "runs").glob("*/results.json")), reverse=True)
if not run_ids:
    st.info("No runs yet. Try: make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1")
    st.stop()

agents = sorted({load_run(r).agent for r in run_ids})
agent = st.sidebar.selectbox("Agent", ["All", *agents])
visible = [r for r in run_ids if agent == "All" or f"_{agent}_" in r]
run = load_run(st.sidebar.selectbox("Run", visible))

runs_tab, verdict_tab = st.tabs(["Runs", "Verdict"])

# --- Runs tab: totals, one row per case, then one expandable panel per case ---------------------

with runs_tab:
    counts = {s: sum(c.status == s for c in run.cases) for s in ("pass", "fail", "error")}
    cols = st.columns(5)
    cols[0].metric("Agent / suite", f"{run.agent} / {run.suite}")
    cols[1].metric("Build", run.build or "-")
    cols[2].metric("Passed", f"{counts['pass']} / {len(run.cases)}")
    cols[3].metric("Failed", counts["fail"])
    cols[4].metric("Errors", counts["error"])
    st.caption(f"{run.run_id} · started {run.started_at} · {'offline (saved traces)' if run.offline else 'live'}"
               f" · {run.reps} rep(s)")

    st.dataframe(pd.DataFrame([{
        "case": c.case_id,
        "rep": c.rep + 1,
        "status": c.status.upper(),
        "failed": ", ".join(r.name for r in c.results if r.status in ("fail", "error")) or c.error,
        "skipped judges": ", ".join(r.name for r in c.results if r.status == "skip"),
        "latency ms": c.latency_ms,
    } for c in run.cases]), hide_index=True, width="stretch")

    for case in run.cases:
        label = f"{case.status.upper()} · {case.case_id}" + (f" · rep {case.rep + 1}" if run.reps > 1 else "")
        with st.expander(label, expanded=case.status != "pass"):
            if case.error:
                st.error(case.error)
            left, right = st.columns(2)
            left.markdown("**Question**")
            left.write(case.question or "-")
            left.markdown("**Agent answer**")
            left.text(case.answer or "-")
            if case.expected_answer:
                right.markdown("**Expected answer**")
                right.text(case.expected_answer)
            right.markdown("**Checks and judges**")
            right.dataframe(pd.DataFrame([{
                "status": r.status.upper(), "type": r.kind, "name": r.name,
                "score": r.score, "threshold": r.threshold, "engine": r.engine, "reason": r.reason,
            } for r in case.results]), hide_index=True, width="stretch")
            if case.trace:
                st.caption(f"Trace: {case.trace}")

# --- Verdict tab: the same comparison as `make verdict`, for the selected run -------------------
with verdict_tab:
    path = baseline_path(run.agent, run.suite)
    if not path.is_file():
        st.info(f"No baseline for {run.agent}/{run.suite} yet. "
                f"Create one: make baseline AGENT={run.agent} SUITE={run.suite} BUILD=<stable build> REPS=5")
    else:
        passed, rows, baseline = compare(run)
        st.subheader(("PASS - no regressions" if passed else "FAIL - regressions found")
                     + f"  (build {run.build or '?'} vs baseline {baseline.get('build') or '?'})")
        st.dataframe(pd.DataFrame([{
            "status": r["status"].upper(),
            "case :: result": r["result"],
            "baseline pass rate": (r["baseline"] or {}).get("pass_rate"),
            "current pass rate": (r["current"] or {}).get("pass_rate"),
            "baseline score": (r["baseline"] or {}).get("mean_score"),
            "current score": (r["current"] or {}).get("mean_score"),
            "note": r["note"],
        } for r in rows]), hide_index=True, width="stretch")
