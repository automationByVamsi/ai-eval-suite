"""
Reading the saved runs for the dashboard: outputs/runs/<run id>/results.json, and how each run is named
in the sidebar menu.

Used by: dashboard.py and dashboard_run.py.
"""

import json

import pandas as pd
import streamlit as st

from src.core import paths
from src.core.results import PASS, Run, load_run


def all_run_ids() -> list[str]:
    """The id of every saved run, newest first (run ids start with the date and time)."""
    return sorted((p.parent.name for p in (paths.OUTPUTS_DIR / "runs").glob("*/results.json")), reverse=True)


@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float) -> Run:          # mtime: re-read when the file changes
    return load_run(path)


def load(run_id: str) -> Run:
    """One saved run. Cached, and read again when its file changes."""
    path = paths.OUTPUTS_DIR / "runs" / run_id / "results.json"
    return _load(str(path), path.stat().st_mtime)


def run_label(run_id: str) -> str:
    """How a run appears in the sidebar's "Run" menu: when, how many passed, which build."""
    run = load(run_id)
    stamp = pd.to_datetime(run.started_at).strftime("%d %b %H:%M") if run.started_at else run_id[:15]
    passed = sum(c.status == PASS for c in run.cases)
    build = f" · build {run.build}" if run.build else ""
    if run.kind == "verdict" and (outcome := _verdict_outcome(run_id)):
        word = "PASS" if outcome.get("passed") else "FAIL"
        against = (outcome.get("baseline") or {}).get("build") or "?"
        return f"⚖ VERDICT {word} · {run.build or '?'} vs {against} · {stamp}"
    if run.kind == "baseline":
        return f"★ BASELINE{build} · {stamp} · {passed}/{len(run.cases)} passed"
    return f"{stamp} · {passed}/{len(run.cases)} passed{build}"


def _verdict_outcome(run_id: str) -> dict | None:
    """verdict.json of a run saved by `make verdict` (None for any other run)."""
    path = paths.OUTPUTS_DIR / "runs" / run_id / "verdict.json"
    return json.loads(path.read_text()) if path.is_file() else None
