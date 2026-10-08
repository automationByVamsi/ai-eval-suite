"""
The "Consistency" tab of the run page. It only appears for runs where every case was asked more than once
(REPS > 1). For each case it shows whether the repeated runs agreed, which pages each run used, and what
each run answered.

Used by: dashboard_run.py. The numbers come from release.consistency().
"""

import streamlit as st

from src.core.results import ERROR, FAIL, PASS, SKIP, CaseResult, Run
from src.reporting import dashboard_parts as ui
from src.reporting import release
from src.reporting.dashboard_style import html


def show_consistency_tab(run: Run, consistency_rows: list[dict]) -> None:
    """The whole tab: a one-line rule, then one accordion per case."""
    spec = run.consistency or {}
    reps_by_case: dict[str, list[CaseResult]] = {}      # case id -> its runs
    for c in run.cases:
        reps_by_case.setdefault(c.case_id, []).append(c)

    st.caption(f"Each case was asked {run.reps} times. {consistency_rule(spec)}")
    for row in consistency_rows:
        reps = sorted(reps_by_case[row["case"]], key=lambda c: c.rep)
        show_case(row, reps, spec)


def consistency_rule(spec: dict) -> str:
    """The rule in words, from agent.yaml `consistency:`."""
    parts = []
    if spec.get("same"):
        parts.append(f"the {release.field_label(spec['same'])} are the same in every run")
    names = spec.get("all_pass") or ["every LLM judge"]
    parts.append(f"{', '.join(ui.label(n).lower() for n in names)} passes in every run")
    return "A case is consistent when " + " and ".join(parts) + ". The wording of the answer may differ."


def friendly(reason: str) -> str:
    """'case has no expected_answer' -> 'no reference answer' (other reasons as they are)."""
    return "no reference answer" if "expected_answer" in reason else reason


def show_case(row: dict, reps: list[CaseResult], spec: dict) -> None:
    """One case: an accordion that is open when the case was inconsistent."""
    ok = row["consistent"]
    title = (f":{'green' if ok else 'red'}[**{'CONSISTENT' if ok else 'INCONSISTENT'}**]  ·  "
             f"**{row['case']}**  ·  {case_headline(row, ok)}")
    with st.expander(title, icon=":material/check_circle:" if ok else ":material/cancel:", expanded=not ok):
        html(f'<div class="question">{ui.esc(reps[0].question or "-")}</div>')
        show_stats_line(row, spec)
        show_pages_grid(reps)
        show_each_run(reps)


def case_headline(row: dict, ok: bool) -> str:
    """The short sentence after the case name, e.g. 'same pages in every run'."""
    if ok:
        headline = (f"same {release.field_label(row['same'])} in every run" if row["same"]
                    else "same result in every run")
    else:
        headline = row["why"]
    # judges that could not give a verdict are added to the end
    headline += "".join(f" · {ui.label(n).lower()} not judged ({friendly(why)})"
                        for n, why in row["not_judged"].items())
    return headline


def show_stats_line(row: dict, spec: dict) -> None:
    """The row of small chips: how much the runs had in common, how often each judge passed."""
    chips = []
    if row["same"]:
        overlap = row["overlap"]
        chips.append(ui.chip(f"{release.field_label(row['same'])}: {overlap:.0%} in common",
                             "good-soft" if overlap >= spec.get("min_overlap", 1.0) else "bad-soft"))
    for name, value in row["passes"].items():          # value looks like "3/5"
        k, n = (int(x) for x in value.split("/"))
        chips.append(ui.chip(f"{ui.label(name).lower()} passed {k} of {n}",
                             "good-soft" if k == n else "bad-soft"))
    for name, why in row["not_judged"].items():
        chips.append(ui.chip(f"{ui.label(name).lower()}: not judged ({friendly(why)})", "ghost"))
    for field, overlap in row["also"].items():
        chips.append(ui.chip(f"{release.field_label(field)}: {overlap:.0%} in common", "ghost"))
    html(f'<div class="stat-line">{"".join(chips)}</div>')


def show_pages_grid(reps: list[CaseResult]) -> None:
    """A grid of pages (rows) against runs (columns), if the agent reported any pages."""
    grid = ui.pages_by_run(reps)
    if not grid:
        return
    html('<div class="card-label">Pages used in each run</div>')
    html(ui.pages_grid_html(grid, len(reps)))
    st.caption("anchor = the main page the answer is built on · expanded = related page added · "
               "cited = referenced in the answer · used = in the evidence list only. "
               "Highlighted rows changed between runs.")


def show_each_run(reps: list[CaseResult]) -> None:
    """One small tab per run, holding that run's answer and scores."""
    html('<div class="card-label" style="margin-top:14px">The answer in each run</div>')
    for tab, case in zip(st.tabs([f"Run {c.rep + 1}" for c in reps]), reps, strict=True):
        with tab:
            render_repetition(case)


def render_repetition(case: CaseResult) -> None:
    """One run of a repeated case: its answer, confidence, latency and scores."""
    d = case.details or {}
    meta = [ui.chip(case.status.upper(), {PASS: "good-soft", FAIL: "bad-soft", ERROR: "warn-soft"}[case.status])]
    if d.get("confidence"):
        conf = str(d["confidence"]).upper()
        meta.append(ui.chip(f"confidence: {conf}",
                            {"HIGH": "good-soft", "MEDIUM": "warn-soft", "LOW": "bad-soft"}.get(conf, "plain")))
    if case.latency_ms:
        meta.append(ui.chip(f"{case.latency_ms / 1000:.1f}s"))
    for r in ui.split(case)[0]:                         # the LLM judges
        if r.score is not None:
            kind = "good-soft" if r.status == PASS else "bad-soft"
            meta.append(ui.chip(f"{ui.label(r.name).lower()} {r.score:.2f}", kind, title=r.reason))
        elif r.status == SKIP:
            meta.append(ui.chip(f"{ui.label(r.name).lower()} not judged", "ghost", title=r.reason))
    html(f'<div class="stat-line">{"".join(meta)}</div>')
    if case.error:
        html(f'<div class="problem-reason">{ui.esc(case.error)}</div>')
    st.markdown(case.answer or "_No answer._")
    for note in [*(ui.as_list(d.get("caveats"))), *(ui.as_list(d.get("user_warnings")))]:
        st.caption(f":material/info: {note}")
