"""
The test-case list of the dashboard: one expander per case, with what was asked and answered on the left
and the LLM judges and deterministic checks on the right.

Used by: dashboard.py (the "Test cases" tab) and dashboard_verdict.py (its "This build" / "Baseline build" tabs).
"""

import altair as alt
import pandas as pd
import streamlit as st

from src.core.results import ERROR, FAIL, PASS, SKIP, CaseResult, Run
from src.reporting import dashboard_parts as ui
from src.reporting.dashboard_style import html

PAGE_SIZE = 25          # cases / rows shown per page


def matches(case: CaseResult, status_filter: list | None, search: str) -> bool:
    """True when the case passes the sidebar filters: its status is ticked and the search text is in it."""
    wanted = {s.lower() for s in (status_filter or [])}
    if case.status not in wanted:
        return False
    text = search.strip().casefold()
    return not text or any(text in (v or "").casefold() for v in (case.case_id, case.question, case.answer))


def case_header(case: CaseResult, reps: int) -> tuple[str, str]:
    """The one-line title of a case's accordion, and its icon: status, id, question, judge / check tallies."""
    judges, groups = ui.split(case)
    checks = [r for g in groups.values() for r in g]
    color = {PASS: "green", FAIL: "red", ERROR: "orange"}[case.status]
    icon = {PASS: ":material/check_circle:", FAIL: ":material/cancel:", ERROR: ":material/error:"}[case.status]
    question = ui.short(case.question or case.description or "", 80)
    bits = [f":{color}[**{case.status.upper()}**]", f"**{case.case_id}**"]
    if reps > 1:
        bits.append(f"rep {case.rep + 1}")
    bits.append(question)
    tail = []
    if judges:
        tail.append(f"judges {ui.ran(ui.tally(judges))}")
    if checks:
        tail.append(f"checks {ui.ran(ui.tally(checks))}")
    if case.latency_ms:
        tail.append(f"{case.latency_ms / 1000:.1f}s")
    return "  ·  ".join(bits) + ("  —  " + " · ".join(tail) if tail else ""), icon


def render_left(case: CaseResult, col) -> None:
    """Left column of a case: the question, the agent's answer, the expected answer and the pages behind it."""
    d = case.details or {}
    with col.container(border=True):
        html('<div class="card-label">Question</div>')
        html(f'<div class="question">{ui.esc(case.question or "-")}</div>')
        extra = {k: v for k, v in case.input.items() if k != "question" and v not in (None, "")}
        if extra or case.description:
            html('<div class="chips">' + "".join(ui.chip(f"{k}: {ui.short(v, 40)}") for k, v in extra.items())
                 + "</div>" + (f'<div class="row-reason">{ui.esc(case.description)}</div>' if case.description else ""))
    with col.container(border=True):
        meta = []
        if d.get("question_type"):
            meta.append(ui.chip(f"type: {d['question_type']}", "accent"))
        if d.get("confidence"):
            conf = str(d["confidence"]).upper()
            meta.append(ui.chip(f"confidence: {conf}",
                                {"HIGH": "good-soft", "MEDIUM": "warn-soft", "LOW": "bad-soft"}.get(conf, "plain")))
        html(f'<div class="card-label">Agent answer<span class="count">{"".join(meta)}</span></div>')
        if case.answer:
            st.markdown(case.answer)
        else:
            html('<div class="note">No answer.</div>')
        notes = [*(d.get("caveats") or []), *(d.get("user_warnings") or [])]
        for note in notes if isinstance(notes, list) else []:
            st.caption(f":material/info: {note}")
    with col.container(border=True):
        html('<div class="card-label">Expected answer (reference)</div>')
        if case.expected_answer:
            st.markdown(case.expected_answer)
        else:
            html('<div class="note">This case has no reference answer, so correctness is skipped.</div>')
    pages = ui.evidence_pages(case)
    missed = ui.expected_pages_missed(case)
    if pages or missed:
        with col.container(border=True):
            roles = ("anchor = chosen first · expanded = related pages added · cited = in the answer · "
                     "expected = a page the test case expects")
            html(f'<div class="card-label">Supporting evidence<span class="count">{len(pages)} page'
                 f'{"s" * (len(pages) != 1)}</span></div>')
            html("".join(ui.page_html(p) for p in pages))
            if missed:
                html(f'<div class="missed">✗ Expected but not in the evidence: {ui.esc(", ".join(missed))}</div>')
            if pages and not any(p["text"] for p in pages):
                html('<div class="note">Page text was not fetched in this suite (no judge needed it).</div>')
            st.caption(roles)


def render_right(case: CaseResult, col, suite_checks: list | None) -> None:
    """Right column of a case: the LLM judges, then the deterministic checks (kept apart)."""
    judges, groups = ui.split(case)
    with col.container(border=True):
        counts = ui.tally(judges)
        html(f'<div class="card-label">LLM judges<span class="count">'
             f'{ui.ran(counts) + " passed" if judges else ""}</span></div>')
        if judges:
            html("".join(ui.judge_html(r) for r in judges))
        else:
            html('<div class="note">This suite runs no LLM judges.</div>')
    with col.container(border=True):
        checks = [r for g in groups.values() for r in g]
        counts = ui.tally(checks)
        skipped = f" · {counts[SKIP]} skipped" if counts[SKIP] else ""
        html(f'<div class="card-label">Deterministic checks<span class="count">'
             f'{ui.ran(counts) + " passed" + skipped if checks else ""}</span></div>')
        if checks:
            html(ui.checks_html(groups))
        elif suite_checks == []:
            html('<div class="note">This suite runs no deterministic checks (checks: none in agent.yaml).</div>')
        else:
            html('<div class="note">No checks ran for this case.</div>')


def render_debug(case: CaseResult) -> None:
    """The tabs under a case for people debugging it: fields, stage timings, the test case, the raw result."""
    fields_tab, timing_tab, case_tab, raw_tab = st.tabs([
        ":material/data_object: Pipeline fields", ":material/timer: Stage timings",
        ":material/description: Test case", ":material/code: Raw result"])
    with fields_tab:
        if case.details:
            st.dataframe(pd.DataFrame([{"field": k, "value": ui.short(v, 300)} for k, v in case.details.items()
                                       if k != "contexts"]),
                         hide_index=True, width="stretch", height=300)
            st.caption("Every field from fields.yaml for this case (make fields shows the same for a saved trace).")
        else:
            st.caption("No fields saved for this case (older run, or the case errored before reading the trace).")
        if case.trace:
            st.caption(f"Trace: `{case.trace}`")
    with timing_tab:
        stages = (case.details or {}).get("stage_seconds")
        if isinstance(stages, dict) and stages:
            frame = pd.DataFrame({"stage": list(stages), "seconds": list(stages.values())})
            st.altair_chart(alt.Chart(frame).mark_bar(cornerRadiusEnd=4, color="#6366f1").encode(
                x=alt.X("seconds:Q", title="seconds"), y=alt.Y("stage:N", sort=None, title=None),
                tooltip=["stage", alt.Tooltip("seconds:Q", format=".2f")]), width="stretch")
        else:
            st.caption("No stage timings in this trace.")
    with case_tab:
        st.json({"input": case.input, "expected": case.expected}, expanded=True)
    with raw_tab:
        st.json({"case_id": case.case_id, "rep": case.rep, "status": case.status, "error": case.error,
                 "results": [r.__dict__ for r in case.results]}, expanded=False)


def render_case_list(r: Run, key: str, status_filter: list | None, search: str) -> None:
    """
    Every test case of a run (filtered by the sidebar), problems first, one expander each.
    key: makes the page number box unique when two lists are on one page (verdict view).
    """
    shown = [c for c in r.cases if matches(c, status_filter, search)]
    shown.sort(key=lambda c: {ERROR: 0, FAIL: 1, PASS: 2}[c.status])
    top = st.columns([3, 1])
    top[0].caption(f"{len(shown)} of {len(r.cases)} cases · problems first · use the sidebar to filter. "
                   "Left: what was asked and answered. Right: LLM judges, then deterministic checks.")
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    page = (top[1].number_input("Page", 1, pages, 1, label_visibility="collapsed", key=f"page_{key}")
            if pages > 1 else 1)
    if not shown:
        st.info("No case matches the filters.")
    for case in shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        title, icon = case_header(case, r.reps)
        with st.expander(title, icon=icon, expanded=len(shown) == 1):
            for problem in ui.problems(case):
                html(ui.problem_html(problem))
            left, right = st.columns([1.15, 1], gap="medium")
            render_left(case, left)
            render_right(case, right, r.checks)
            render_debug(case)
