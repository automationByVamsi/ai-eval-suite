"""Load saved runs (outputs/runs/<run id>/results.json) for the dashboard and label them for the sidebar."""

import json

import pandas as pd
import streamlit as st

from src.core import paths
from src.core.results import PASS, Run, load_run


def all_run_ids() -> list[str]:
    """Return every saved run id, newest first (ids start with the date and time)."""
    return sorted((p.parent.name for p in (paths.OUTPUTS_DIR / "runs").glob("*/results.json")), reverse=True)


@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float) -> Run:
    """Load a run from disk; mtime is in the cache key so a changed file is re-read."""
    return load_run(path)


def load(run_id: str) -> Run:
    """Return one saved run, cached and re-read when its file changes."""
    path = paths.OUTPUTS_DIR / "runs" / run_id / "results.json"
    return _load(str(path), path.stat().st_mtime)


def run_label(run_id: str) -> str:
    """Return a run's label in the sidebar's "Run" menu: when, how many passed, which build."""
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
    """Return the run's verdict.json, or None if it wasn't saved by `make verdict`."""
    path = paths.OUTPUTS_DIR / "runs" / run_id / "verdict.json"
    return json.loads(path.read_text()) if path.is_file() else None
