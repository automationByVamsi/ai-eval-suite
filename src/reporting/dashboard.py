"""
Results dashboard: `make dashboard` (runs `streamlit run src/reporting/dashboard.py`).

Read-only: it reads outputs/runs/*/results.json and baselines/ — nothing else. Tabs:
  Overview    the run at a glance: pass rates, every judge and check across the run, where cases fail
  Test cases  one accordion per case: question, agent answer, expected answer and the pages behind it
              on the left; LLM judges and deterministic checks, kept apart, on the right; errors
              explained (what failed, the message, how to fix) at the top
  Consistency (runs with REPS > 1) per case: which pages each run used (a pages x runs grid) and
              each run's answer and scores, so a reviewer can see what changed
  Trends      the same agent + suite over its recent runs
  Baseline    this run against the agent/suite baseline (same logic as `make verdict`)

A run saved by `make verdict` opens a release view instead (render_verdict): a PASS / FAIL banner, the
headline numbers against the baseline, and the tabs Summary, Comparison (both builds side by side, per
case), This build and Baseline build. Its data comes from src/reporting/verdict_view.py.

The pieces that aren't Streamlit calls (error explanations, HTML blocks) are in dashboard_parts.py.
"""

import json
import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root isn't on the import path; add it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt  # noqa: E402 — must come after the sys.path line above
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.core import paths  # noqa: E402
from src.core.results import ERROR, FAIL, PASS, SKIP, CaseResult, Run, load_run  # noqa: E402
from src.reporting import dashboard_parts as ui  # noqa: E402
from src.reporting import release  # noqa: E402
from src.reporting import verdict_view as vv  # noqa: E402
from src.reporting.dashboard_style import apply_theme, html  # noqa: E402
from src.reporting.summary import summarise  # noqa: E402
from src.verdict.baseline import baseline_path  # noqa: E402
from src.verdict.compare import compare  # noqa: E402

st.set_page_config(page_title="Agent evals", page_icon=":material/fact_check:", layout="wide")

PAGE_SIZE = 25
COLORS = {PASS: "#16a34a", FAIL: "#dc2626", ERROR: "#d97706", SKIP: "#94a3b8"}

apply_theme()                   # the colours and CSS (dashboard_style.py)


# --- loading -------------------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float) -> Run:          # mtime: re-read when the file changes
    return load_run(path)


def load(run_id: str) -> Run:
    path = paths.OUTPUTS_DIR / "runs" / run_id / "results.json"
    return _load(str(path), path.stat().st_mtime)


def run_label(run_id: str) -> str:
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
    path = paths.OUTPUTS_DIR / "runs" / run_id / "verdict.json"
    return json.loads(path.read_text()) if path.is_file() else None


run_ids = sorted((p.parent.name for p in (paths.OUTPUTS_DIR / "runs").glob("*/results.json")), reverse=True)
if not run_ids:
    html('<div class="hero"><div><div class="hero-title">No runs yet</div><div class="hero-sub">'
         'Run a suite, then refresh: <code>make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1</code>'
         '</div></div></div>')
    st.stop()

# --- sidebar: which run, which cases --------------------------------------------------------------

with st.sidebar:
    st.markdown("### :material/fact_check: Agent evals")
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

# --- Test cases ------------------------------------------------------------------------------------


def matches(case: CaseResult) -> bool:
    wanted = {s.lower() for s in (status_filter or [])}
    if case.status not in wanted:
        return False
    text = search.strip().casefold()
    return not text or any(text in (v or "").casefold() for v in (case.case_id, case.question, case.answer))


def case_header(case: CaseResult, reps: int) -> tuple[str, str]:
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


def render_case_list(r: Run, key: str) -> None:
    """Every test case of a run (filtered by the sidebar), problems first, one expander each."""
    shown = [c for c in r.cases if matches(c)]
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


# --- Verdict view (runs saved by `make verdict`) ------------------------------------------------------

CHANGE_STYLE = {   # change -> (label, chip kind, colour token, streamlit colour, icon)
    "regressed": ("Regressed", "bad", "--bad", "red", ":material/trending_down:"),
    "missing": ("Missing", "warn", "--warn", "orange", ":material/help:"),
    "improved": ("Improved", "good", "--good", "green", ":material/trending_up:"),
    "new": ("New", "accent", "--accent", "violet", ":material/fiber_new:"),
    "unchanged": ("Unchanged", "plain", "--muted", "gray", ":material/remove:"),
}
ITEM_KIND = {"regression": "bad-soft", "missing": "warn-soft", "improved": "good-soft", "new": "accent", "ok": "ghost"}


def delta_html(before: float | None, after: float | None, points: bool = True, digits: int = 0) -> str:
    """'▲ 4 pts' (green) / '▼ 0.03' (red) / 'no change' — higher is better for every rate and score here."""
    if before is None or after is None:
        return '<span class="delta flat">no baseline</span>'
    diff = after - before
    if abs(diff) < 0.005:                                   # below what the number shows: no change
        return '<span class="delta flat">no change</span>'
    pts = round(abs(diff) * 100)
    shown = f"{pts} pt{'s' * (pts != 1)}" if points else f"{abs(diff):.{digits or 2}f}"
    return f'<span class="delta {"up" if diff > 0 else "down"}">{"▲" if diff > 0 else "▼"} {shown}</span>'


NO_JUDGES = '<span class="delta flat">no LLM judges in this suite</span>'


def vkpi(label_: str, value: str, sub_html: str, kind: str = "plain") -> str:
    return (f'<div class="kpi {kind}"><div class="kpi-label">{ui.esc(label_)}</div>'
            f'<div class="kpi-value">{ui.esc(value)}</div><div class="kpi-sub">{sub_html}</div></div>')


def change_bar_html(changes: dict) -> str:
    """One stacked bar: how many test cases regressed / improved / ... with a labelled legend."""
    counts = {k: sum(c.change == k for c in changes.values()) for k in vv.CHANGES}
    total = max(sum(counts.values()), 1)
    segments = "".join(f'<div class="seg" style="flex:{n};background:var({CHANGE_STYLE[k][2]})" '
                       f'title="{CHANGE_STYLE[k][0]}: {n}"></div>' for k, n in counts.items() if n)
    legend = "".join(f'<span class="legend-item"><span class="dot" style="background:var({CHANGE_STYLE[k][2]})">'
                     f'</span>{CHANGE_STYLE[k][0]} <b>{n}</b></span>' for k, n in counts.items() if n)
    return (f'<div class="stackbar">{segments}</div><div class="legend">{legend}'
            f'<span class="legend-total">{total} test cases</span></div>')


def targets_compare_html(current_rows: list, baseline_rows: list) -> str:
    """Release targets: target, baseline build, this build, met / missed."""
    before = {r["name"]: r for r in baseline_rows}
    out = ['<table class="grid vt"><tr><th>Release target</th><th>Target</th><th>Baseline</th><th>This build</th>'
           '<th></th></tr>']
    for r in current_rows:
        b = before.get(r["name"])
        sign = "≤" if r["ceiling"] else "≥"
        kind = {True: "good", False: "bad", None: "muted"}[r["met"]]
        word = {True: "met", False: "missed", None: "n/a"}[r["met"]]
        now = "–" if r["actual"] is None else f"{r['actual']:.0%}"
        was = "–" if not b or b["actual"] is None else f"{b['actual']:.0%}"
        trend = "" if not b or b["actual"] is None or r["actual"] is None else delta_html(
            b["actual"] if not r["ceiling"] else -b["actual"], r["actual"] if not r["ceiling"] else -r["actual"])
        out.append(f'<tr><td><span class="row-name">{ui.esc(ui.label(r["name"]))}</span>'
                   f'<div class="row-reason">{ui.esc(r["detail"])}</div></td>'
                   f'<td class="num muted">{sign} {r["target"]:.0%}</td><td class="num">{was}</td>'
                   f'<td class="num"><b>{now}</b> {trend}</td>'
                   f'<td>{ui.chip(word, kind + "-soft" if kind != "muted" else "ghost")}</td></tr>')
    return "".join(out) + "</table>"


def dumbbell(rows: list, value: str, title: str, fmt: str):
    """Baseline (hollow) -> this build (filled), one line per judge / check; colour = better / worse / same."""
    data = []
    for r in rows:
        b, n = r[f"baseline_{value}"], r[f"current_{value}"]
        if n is None and b is None:
            continue
        diff = (n or 0) - (b or 0) if n is not None and b is not None else 0
        move = "better" if diff > 0.005 else "worse" if diff < -0.005 else "same"
        name = ui.label(r["name"])
        data.append({"name": name, "build": "Baseline", "value": b, "move": move, "baseline": b, "current": n})
        data.append({"name": name, "build": "This build", "value": n, "move": move, "baseline": b, "current": n})
    if not data:
        return None
    frame = pd.DataFrame(data)
    order = list(dict.fromkeys(frame["name"]))
    moves = {"better": "#16a34a", "worse": "#dc2626", "same": "#64748b"}
    tooltip = ["name", alt.Tooltip("baseline:Q", format=fmt, title="baseline"),
               alt.Tooltip("current:Q", format=fmt, title="this build"), alt.Tooltip("move:N", title="change")]
    y = alt.Y("name:N", sort=order, title=None,
              axis=alt.Axis(labelLimit=220, labelPadding=8, ticks=False, domain=False))
    x = alt.X("value:Q", title=title, scale=alt.Scale(zero=False, padding=12),
              axis=alt.Axis(format=fmt, grid=True, gridOpacity=0.35, domain=False, tickCount=5))
    line = alt.Chart(frame).mark_line(strokeWidth=3, opacity=0.55).encode(
        x=x, y=y, detail="name:N", color=alt.Color("move:N", scale=alt.Scale(domain=list(moves),
                                                                              range=list(moves.values())), legend=None))
    base_pt = alt.Chart(frame[frame.build == "Baseline"]).mark_point(size=110, filled=True, color="#cbd5e1",
                                                                      stroke="#64748b", strokeWidth=1.5).encode(
        x=x, y=y, tooltip=tooltip)
    now_pt = alt.Chart(frame[frame.build == "This build"]).mark_point(size=150, filled=True, stroke="white",
                                                                       strokeWidth=2).encode(
        x=x, y=y, tooltip=tooltip,
        color=alt.Color("move:N", scale=alt.Scale(domain=list(moves), range=list(moves.values())), legend=None))
    return (line + base_pt + now_pt).properties(height=max(120, 38 * len(order))).configure_view(strokeWidth=0)


def _legend_item(colour: str, text: str, ring: bool = False) -> str:
    dot = '<span class="dot ring"></span>' if ring else f'<span class="dot" style="background:{colour}"></span>'
    return f'<span class="legend-item">{dot}{text}</span>'


DUMBBELL_LEGEND = ('<div class="legend" style="margin:2px 0 6px">' + _legend_item("", "baseline", ring=True)
                   + _legend_item("var(--good)", "this build: better") + _legend_item("var(--bad)", "this build: worse")
                   + _legend_item("#64748b", "no change") + "</div>")


def _moved(row: dict, value: str) -> bool:
    b, n = row[f"baseline_{value}"], row[f"current_{value}"]
    return b is None or n is None or abs(n - b) >= 0.005


def compact_build_html(case: CaseResult | None, reps: list) -> str:
    """One build's side of a comparison: status, judges with scores, failed checks."""
    if case is None:
        return '<div class="note">Not in this build.</div>'
    judges, groups = ui.split(case)
    status_kind = {PASS: "good", FAIL: "bad", ERROR: "warn"}[case.status]
    head = [ui.chip(case.status.upper(), status_kind)]
    if len(reps) > 1:
        passed = sum(c.status == PASS for c in reps)
        head.append(ui.chip(f"{passed}/{len(reps)} reps passed", "good-soft" if passed == len(reps) else "bad-soft"))
    if case.latency_ms:
        head.append(ui.chip(f"{case.latency_ms / 1000:.1f}s"))
    out = [f'<div class="stat-line">{"".join(head)}</div>']
    for r in judges:
        kind = {PASS: "good", FAIL: "bad"}.get(r.status, "muted")
        score = f"{r.score:.2f}" if r.score is not None else r.status
        mark = {PASS: "✓", FAIL: "✗"}.get(r.status, "–")
        out.append(f'<div class="vrow"><span class="icon {kind}">{mark}'
                   f'</span><span class="row-name">{ui.esc(ui.label(r.name))}</span>'
                   f'<span class="score {kind}">{ui.esc(score)}</span></div>')
    failed = [r for g in groups.values() for r in g if r.status in (FAIL, ERROR)]
    checks = [r for g in groups.values() for r in g if r.status in (PASS, FAIL)]
    if checks:
        out.append(f'<div class="vsub">Checks: {sum(r.status == PASS for r in checks)}/{len(checks)} passed</div>')
    for r in failed:
        out.append(f'<div class="vrow"><span class="icon bad">✗</span><div><span class="row-name">'
                   f'{ui.esc(ui.label(r.name))}</span><div class="row-reason">{ui.esc(ui.short(r.reason, 160))}</div>'
                   f'</div></div>')
    return "".join(out)


def render_side(case: CaseResult | None, reps: list, col, title: str) -> None:
    with col.container(border=True):
        html(f'<div class="card-label">{ui.esc(title)}</div>')
        html(compact_build_html(case, reps))
    if case is None:
        return
    with col.container(border=True, height=280):
        html('<div class="card-label">Answer</div>')
        st.markdown(case.answer or "_No answer._")
    pages = ui.evidence_pages(case)
    if pages:
        with col.container(border=True):
            html(f'<div class="card-label">Pages used<span class="count">{len(pages)}</span></div>')
            html("".join(ui.page_html(p) for p in pages))


def render_verdict(v: "vv.Verdict") -> None:
    current, base = v.run, v.baseline_run
    outcome = v.outcome
    changes = vv.case_changes(outcome.get("rows") or [])
    now_stats = ui.run_stats(current)
    was_stats = ui.run_stats(base) if base else None
    gate_ok, target_rows = release.gate(current)
    base_targets = release.gate(base)[1] if base else []
    missed = sum(r["met"] is False for r in target_rows)
    reason = vv.headline(outcome, changes, now_stats["errors"], missed)

    # Hero ----------------------------------------------------------------------------------------
    good = v.passed
    when = pd.to_datetime(outcome.get("decided_at") or current.started_at)
    chips = "".join(ui.chip(x, k) for x, k in [
        (current.suite, "accent"), (f"{current.reps} rep{'s' * (current.reps > 1)} per case", "plain"),
        ("offline replay" if current.offline else "live agent", "plain"),
        (f"judge temperature {current.judge_temperature}" if current.judge_temperature is not None else "", "plain"),
        (f"{when:%d %b %Y, %H:%M}", "ghost"), (current.run_id, "ghost")] if x)
    html(f'<div class="vhero {"good" if good else "bad"}">'
         f'<div class="vhero-main"><div class="eyebrow">Release verdict · '
         f'{ui.esc(current.agent.replace("_", " ").title())}</div>'
         f'<div class="vhero-title">Build <b>{ui.esc(current.build or "?")}</b>'
         f'<span class="vs">vs baseline</span><b>{ui.esc(v.baseline_build)}</b></div>'
         f'<div class="vhero-reason">{ui.esc(reason)}</div><div class="hero-sub">{chips}</div></div>'
         f'<div class="vbadge {"good" if good else "bad"}"><div class="vbadge-word">{"PASS" if good else "FAIL"}</div>'
         f'<div class="vbadge-note">{"ready to release" if good else "not ready to release"}</div></div></div>')

    # KPIs ----------------------------------------------------------------------------------------
    regressed = sum(c.change == "regressed" for c in changes.values())
    improved = sum(c.change == "improved" for c in changes.values())
    cases_now = now_stats["passed"] / max(now_stats["cases"], 1)
    cases_was = was_stats["passed"] / max(was_stats["cases"], 1) if was_stats else None
    html('<div class="kpis">' + "".join([
        vkpi("Cases passing", f"{now_stats['passed']}/{now_stats['cases']}",
             (f"baseline {was_stats['passed']}/{was_stats['cases']} · " if was_stats else "")
             + delta_html(cases_was, cases_now), ui.tone(cases_now)),
        vkpi("LLM judge pass rate", ui.pct(now_stats["judge_rate"]),
             NO_JUDGES if now_stats["judge_rate"] is None else
             (f"baseline {ui.pct(was_stats['judge_rate'])} · " if was_stats else "")
             + delta_html(was_stats["judge_rate"] if was_stats else None, now_stats["judge_rate"]),
             ui.tone(now_stats["judge_rate"])),
        vkpi("Mean judge score", "–" if now_stats["mean_score"] is None else f"{now_stats['mean_score']:.2f}",
             NO_JUDGES if now_stats["mean_score"] is None else
             (f"baseline {was_stats['mean_score']:.2f} · " if was_stats and was_stats["mean_score"] is not None
              else "") + delta_html(was_stats["mean_score"] if was_stats else None, now_stats["mean_score"],
                                    points=False), "accent"),
        vkpi("Regressed cases", str(regressed), f"of {len(changes)} test cases got worse",
             "bad" if regressed else "good"),
        vkpi("Improved cases", str(improved), f"of {len(changes)} test cases got better",
             "good" if improved else "plain"),
    ]) + "</div>")

    tab_summary, tab_compare, tab_now, tab_base = st.tabs([
        ":material/insights: Summary", f":material/compare_arrows: Comparison ({len(changes)})",
        f":material/new_releases: This build · {current.build or '?'} ({len(current.cases)})",
        f":material/history: Baseline build · {v.baseline_build} ({len(base.cases) if base else 0})"])

    # Summary -------------------------------------------------------------------------------------
    with tab_summary:
        with st.container(border=True):
            html('<div class="card-label">How the test cases moved<span class="count">per test case, all '
                 'judges and checks together</span></div>')
            html(change_bar_html(changes))
        if target_rows:
            with st.container(border=True):
                status = ui.chip("all targets met", "good") if gate_ok else ui.chip(f"{missed} target(s) missed", "bad")
                html(f'<div class="card-label">Release targets<span class="count">{status}</span></div>')
                html(targets_compare_html(target_rows, base_targets))
        metrics = vv.metric_changes(base, current)
        left, right = st.columns(2, gap="medium")
        with left.container(border=True):
            html('<div class="card-label">LLM judges<span class="count">mean score · baseline → this build'
                 '</span></div>')
            chart = dumbbell([m for m in metrics if m["kind"] == "judge"], "score", "mean score", ".2f")
            if chart is not None:
                html(DUMBBELL_LEGEND)
                st.altair_chart(chart, width="stretch")
            else:
                html('<div class="note">No LLM judges in this verdict.</div>')
        with right.container(border=True):
            html('<div class="card-label">Deterministic checks<span class="count">pass rate · baseline → this '
                 'build</span></div>')
            checks = [m for m in metrics if m["kind"] == "check"]
            moved = [m for m in checks if _moved(m, "rate")]
            chart = dumbbell(moved, "rate", "pass rate", ".0%")
            if chart is not None:
                html(DUMBBELL_LEGEND)
                st.altair_chart(chart, width="stretch")
            still = [m for m in checks if not _moved(m, "rate")]
            if still:
                rates = sorted({ui.pct(m["current_rate"]) for m in still})
                html(f'<div class="note" style="margin-top:6px">{len(still)} other check'
                     f'{"s" * (len(still) != 1)} unchanged (at {", ".join(rates)}): '
                     f'{ui.esc(", ".join(ui.label(m["name"]).lower() for m in still))}.</div>')
            if not checks:
                html('<div class="note">No deterministic checks ran.</div>')
        changed = [c for c in changes.values() if c.change != "unchanged"]
        changed.sort(key=lambda c: vv.CHANGES.index(c.change))
        st.markdown('<div class="section-title">What changed</div><div class="section-note">Every test case whose '
                    'results moved beyond the tolerance (pass rate ±{:.0f} pts, mean score ±{:.2f}). Open the '
                    'Comparison tab to see both answers side by side.</div>'.format(
                        (outcome.get("tolerances") or {}).get("pass_rate_drop", 0.15) * 100,
                        (outcome.get("tolerances") or {}).get("score_drop", 0.10)), unsafe_allow_html=True)
        questions = {c.case_id: c.question for c in [*current.cases, *(base.cases if base else [])]}
        if changed:
            rows_html = []
            for c in changed:
                label_, kind, *_ = CHANGE_STYLE[c.change]
                items = "".join(ui.chip(vv.describe(i), ITEM_KIND.get(i["status"], "ghost"), title=i.get("note", ""))
                                for i in c.items if i["status"] != "ok")
                rows_html.append(f'<div class="vchange"><div class="vchange-head">{ui.chip(label_, kind)}'
                                 f'<span class="row-name">{ui.esc(c.case_id)}</span><span class="row-reason">'
                                 f'{ui.esc(ui.short(questions.get(c.case_id, ""), 110))}</span></div>'
                                 f'<div class="chips">{items}</div></div>')
            html("".join(rows_html))
        else:
            st.success("No test case moved beyond the tolerance: this build behaves like the baseline.",
                       icon=":material/verified:")
        notes = sorted({r["note"] for r in outcome.get("rows") or [] if r.get("note")})
        for note in notes:
            st.warning(note, icon=":material/warning:")
        if not v.outcome.get("has_baseline_run"):
            st.info("This baseline was saved before full baseline runs were kept, so only its numbers are shown. "
                    "Save a new baseline (`make baseline`) to compare test cases side by side.")

    # Comparison ----------------------------------------------------------------------------------
    with tab_compare:
        names = sorted({n for c in changes.values() for n in c.results})
        f1, f2, f3 = st.columns([2.2, 1.6, 1.4])
        picked = f1.pills("Change", [CHANGE_STYLE[k][0] for k in vv.CHANGES], selection_mode="multi",
                          default=[CHANGE_STYLE[k][0] for k in vv.CHANGES], key="v_change")
        wanted_results = f2.multiselect("Judge or check that changed", names, key="v_results",
                                        format_func=lambda n: ("judge · " if n.startswith("judge:") else "check · ")
                                        + ui.label(n.partition(":")[2]), placeholder="any judge or check")
        text = f3.text_input("Search", placeholder="case id or question", key="v_search").strip().casefold()
        picked_keys = {k for k in vv.CHANGES if CHANGE_STYLE[k][0] in (picked or [])}
        by_id_now, by_id_base = _by_case(current), _by_case(base)

        def keep(c) -> bool:
            if c.change not in picked_keys:
                return False
            if wanted_results and not any(i["name"] in wanted_results for i in c.items if i["status"] != "ok"):
                return False
            question = questions.get(c.case_id, "")
            return not text or text in c.case_id.casefold() or text in question.casefold()

        shown = sorted((c for c in changes.values() if keep(c)), key=lambda c: (vv.CHANGES.index(c.change), c.case_id))
        st.caption(f"{len(shown)} of {len(changes)} test cases · worst first")
        if shown:
            st.dataframe(pd.DataFrame([{
                "change": CHANGE_STYLE[c.change][0], "case": c.case_id,
                "question": questions.get(c.case_id, ""),
                "baseline": _status_text(by_id_base.get(c.case_id)),
                "this build": _status_text(by_id_now.get(c.case_id)),
                "what changed": " · ".join(vv.describe(i) for i in c.items if i["status"] != "ok") or "–",
            } for c in shown]), hide_index=True, width="stretch", height=min(38 + 35 * len(shown), 420),
                column_config={"question": st.column_config.TextColumn(width="large"),
                               "what changed": st.column_config.TextColumn(width="large")})
            pages = max(1, -(-len(shown) // PAGE_SIZE))
            page = st.number_input("Page", 1, pages, 1, key="v_page") if pages > 1 else 1
            for c in shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
                label_, _, _, colour, icon = CHANGE_STYLE[c.change]
                moved = " · ".join(vv.describe(i) for i in c.items if i["status"] != "ok")
                title = (f":{colour}[**{label_.upper()}**]  ·  **{c.case_id}**  ·  "
                         f"{ui.short(questions.get(c.case_id, ''), 70)}" + (f"  —  {moved}" if moved else ""))
                with st.expander(title, icon=icon, expanded=len(shown) == 1):
                    if c.items:
                        html('<div class="chips">' + "".join(
                            ui.chip(vv.describe(i), ITEM_KIND.get(i["status"], "ghost"), title=i.get("note", ""))
                            for i in c.items) + "</div>")
                    html(f'<div class="question" style="margin:8px 0 12px">'
                         f'{ui.esc(questions.get(c.case_id, ""))}</div>')
                    left, right = st.columns(2, gap="medium")
                    base_reps, now_reps = by_id_base.get(c.case_id, []), by_id_now.get(c.case_id, [])
                    render_side(base_reps[0] if base_reps else None, base_reps, left,
                                f"Baseline · build {v.baseline_build}")
                    render_side(now_reps[0] if now_reps else None, now_reps, right,
                                f"This build · {current.build or '?'}")
        else:
            st.info("No test case matches the filters.")

    with tab_now:
        render_case_list(current, "verdict_now")
    with tab_base:
        if base:
            render_case_list(base, "verdict_base")
        else:
            st.info("The full baseline run isn't available for this verdict (the baseline was saved before full runs "
                    "were kept). Save a new baseline with `make baseline` to see it here.")


def _by_case(r: Run | None) -> dict[str, list[CaseResult]]:
    out: dict[str, list[CaseResult]] = {}
    for c in (r.cases if r else []):
        out.setdefault(c.case_id, []).append(c)
    return {k: sorted(v, key=lambda c: c.rep) for k, v in out.items()}


def _status_text(reps: list | None) -> str:
    if not reps:
        return "–"
    if len(reps) == 1:
        return reps[0].status.upper()
    return f"{sum(c.status == PASS for c in reps)}/{len(reps)} passed"


# --- the selected run -------------------------------------------------------------------------------

run = load(run_id)

verdict = vv.load(run)
if verdict is not None:
    render_verdict(verdict)
    st.stop()
stats = ui.run_stats(run)
summary = summarise([run])

# --- header ----------------------------------------------------------------------------------------

mode = "offline replay" if run.offline else "live agent"
sub = "".join(ui.chip(x, k) for x, k in [
    (run.suite, "accent"), (f"build {run.build}" if run.build else "no build label", "plain"), (mode, "plain"),
    (f"{run.reps} rep{'s' * (run.reps > 1)}", "plain"),
    (pd.to_datetime(run.started_at).strftime("%d %b %Y, %H:%M") if run.started_at else "", "ghost"),
    (run.run_id, "ghost")] if x)
if stats["errors"]:
    word, kind = f"{stats['errors']} case{'s' * (stats['errors'] > 1)} could not be evaluated", "warn"
elif stats["failed"]:
    word, kind = f"{stats['failed']} of {stats['cases']} cases failed", "bad"
else:
    word, kind = "All cases passed", "good"
judges_line = ", ".join(run.metrics) if run.metrics else "none"
checks_line = "all" if run.checks is None else ("none" if not run.checks else ", ".join(run.checks))
html(f'<div class="hero"><div><div class="hero-title">{ui.esc(run.agent.replace("_", " ").title())}</div>'
     f'<div class="hero-sub">{sub}</div></div>'
     f'<div class="verdict"><span class="verdict-word {kind}">{ui.esc(word)}</span>'
     f'<div class="verdict-note">LLM judges: {ui.esc(judges_line)} · checks: {ui.esc(checks_line)}</div>'
     f'</div></div>')

consistency_rows = release.consistency(run) if run.reps > 1 else []
tab_names = [":material/dashboard: Overview", f":material/list_alt: Test cases ({len(run.cases)})",
             ":material/trending_up: Trends", ":material/compare_arrows: Baseline"]
if consistency_rows:
    tab_names.insert(2, ":material/repeat: Consistency")
tabs = st.tabs(tab_names)
overview_tab, cases_tab = tabs[0], tabs[1]
consistency_tab = tabs[2] if consistency_rows else None
trends_tab, baseline_tab = tabs[-2], tabs[-1]

# --- Overview --------------------------------------------------------------------------------------

with overview_tab:
    case_rate = stats["passed"] / stats["cases"] if stats["cases"] else None
    judged = stats["judges"][PASS] + stats["judges"][FAIL]
    checked = stats["checks"][PASS] + stats["checks"][FAIL]
    mean = f" · mean score {stats['mean_score']:.2f}" if stats["mean_score"] is not None else ""
    latency = f"{stats['median_s']:.1f}s" if stats["median_s"] is not None else "–"
    html('<div class="kpis">' + "".join([
        ui.kpi("Cases passing", ui.pct(case_rate), f"{stats['passed']} of {stats['cases']} test cases",
               ui.tone(case_rate)),
        ui.kpi("LLM judges", ui.pct(stats["judge_rate"]), f"{stats['judges'][PASS]}/{judged} verdicts passed{mean}",
               ui.tone(stats["judge_rate"])),
        ui.kpi("Deterministic checks", ui.pct(stats["check_rate"]),
               f"{stats['checks'][PASS]}/{checked} passed · {stats['checks'][SKIP]} skipped",
               ui.tone(stats["check_rate"])),
        ui.kpi("Could not evaluate", str(stats["errors"]), "cases with an error (not counted as fails)",
               "warn" if stats["errors"] else "good"),
        ui.kpi("Latency", latency, f"median · p95 {stats['p95_s']:.1f}s" if stats["p95_s"] else "median",
               "accent"),
    ]) + "</div>")

    gate_ok, target_rows = release.gate(run)
    if target_rows:
        with st.container(border=True):
            missed = sum(r["met"] is False for r in target_rows)
            status = ui.chip("all targets met", "good") if gate_ok else ui.chip(f"{missed} target(s) missed", "bad")
            html(f'<div class="card-label">Release targets<span class="count">{status}</span></div>')
            html(ui.targets_html(target_rows))
    if consistency_rows:
        with st.container(border=True):
            ok, total = sum(r["consistent"] for r in consistency_rows), len(consistency_rows)
            badge = ui.chip(f"{ok} of {total} cases consistent", "good" if ok == total else "bad")
            html(f'<div class="card-label">Consistency over {run.reps} runs<span class="count">{badge}</span></div>')
            bad = [r for r in consistency_rows if not r["consistent"]]
            for r in bad:
                html(f'<div class="check"><span class="icon bad">✗</span><div><span class="row-name">'
                     f'{ui.esc(r["case"])}</span><div class="row-reason">{ui.esc(r["why"])}</div></div></div>')
            if not bad:
                html('<div class="note">Every case gave the same result in every run.</div>')
            st.caption("The Consistency tab shows the pages and the answer of every run.")

    left, right = st.columns(2, gap="large")
    with left.container(border=True):
        html('<div class="card-label">LLM judges<span class="count">pass rate across cases</span></div>')
        html(ui.scoreboard_html(summary, "judge"))
    with right.container(border=True):
        html('<div class="card-label">Deterministic checks<span class="count">pass rate across cases'
             '</span></div>')
        html(ui.check_scoreboard_html(summary))

    attention = [c for c in run.cases if c.status != PASS]
    st.markdown('<div class="section-title">Needs attention</div>'
                '<div class="section-note">Every case that failed or could not be evaluated, with the first reason.'
                ' Open it in the Test cases tab for the full picture.</div>', unsafe_allow_html=True)
    if attention:
        st.dataframe(pd.DataFrame([{
            "status": c.status.upper(), "case": c.case_id + (f" · rep {c.rep + 1}" if run.reps > 1 else ""),
            "question": c.question, "why": ui.first_issue(c),
            "judges": ui.ran(ui.tally(ui.split(c)[0])),
            "checks": ui.ran(ui.tally([r for g in ui.split(c)[1].values() for r in g])),
        } for c in attention]), hide_index=True, width="stretch",
            column_config={"question": st.column_config.TextColumn(width="large"),
                           "why": st.column_config.TextColumn(width="large")})
    else:
        st.success("Nothing to look at: every case passed.", icon=":material/celebration:")

    cells = [{"case": c.case_id + (f" r{c.rep + 1}" if run.reps > 1 else ""), "result": ui.label(r.name),
              "kind": "LLM judge" if r.kind == "judge" else "check", "status": r.status,
              "detail": r.reason or ("passed" if r.status == PASS else "")}
             for c in run.cases for r in c.results if not ui.is_setup(r)]
    for c in run.cases:                        # a first column: could the case be evaluated at all?
        trouble = ui.problems(c)
        cells.append({"case": c.case_id + (f" r{c.rep + 1}" if run.reps > 1 else ""), "result": "Agent & setup",
                      "kind": "setup", "status": ERROR if trouble else PASS,
                      "detail": trouble[0]["title"] if trouble else "the agent answered"})
    if cells:
        st.markdown('<div class="section-title">Every case × every result</div>'
                    '<div class="section-note">Columns: could it be evaluated, then LLM judges, then checks. '
                    'Hover a cell for why.'
                    '</div>', unsafe_allow_html=True)
        frame = pd.DataFrame(cells)
        rank = {"setup": 0, "LLM judge": 1, "check": 2}
        order = list(dict.fromkeys(frame.sort_values("kind", key=lambda k: k.map(rank), kind="stable")["result"]))
        chart = alt.Chart(frame).mark_rect(cornerRadius=3, stroke="white", strokeWidth=1.5).encode(
            x=alt.X("result:N", sort=order, title=None,
                    axis=alt.Axis(labelAngle=-40, labelLimit=180, labelOverlap=False, orient="top")),
            y=alt.Y("case:N", title=None, sort=list(dict.fromkeys(frame["case"])), axis=alt.Axis(labelOverlap=False)),
            color=alt.Color("status:N", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["case", "result", "kind", "status", "detail"],
        ).properties(height=max(160, 28 * frame["case"].nunique()))
        st.altair_chart(chart, width="stretch", height=max(160, 28 * frame["case"].nunique()) + 170)

with cases_tab:
    render_case_list(run, "run")

# --- Consistency (REPS > 1) ---------------------------------------------------------------------------


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


def render_run(case: CaseResult) -> None:
    """One run of a repeated case: its answer, confidence, latency and scores."""
    d = case.details or {}
    meta = [ui.chip(case.status.upper(), {PASS: "good-soft", FAIL: "bad-soft", ERROR: "warn-soft"}[case.status])]
    if d.get("confidence"):
        conf = str(d["confidence"]).upper()
        meta.append(ui.chip(f"confidence: {conf}",
                            {"HIGH": "good-soft", "MEDIUM": "warn-soft", "LOW": "bad-soft"}.get(conf, "plain")))
    if case.latency_ms:
        meta.append(ui.chip(f"{case.latency_ms / 1000:.1f}s"))
    for r in ui.split(case)[0]:
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


if consistency_tab is not None:
    with consistency_tab:
        spec = run.consistency or {}
        reps_by_case: dict[str, list[CaseResult]] = {}
        for c in run.cases:
            reps_by_case.setdefault(c.case_id, []).append(c)
        st.caption(f"Each case was asked {run.reps} times. {consistency_rule(spec)}")
        for row in consistency_rows:
            reps = sorted(reps_by_case[row["case"]], key=lambda c: c.rep)
            ok = row["consistent"]
            if ok:
                headline = (f"same {release.field_label(row['same'])} in every run" if row["same"]
                            else "same result in every run")
            else:
                headline = row["why"]
            headline += "".join(f" · {ui.label(n).lower()} not judged ({friendly(why)})"
                                for n, why in row["not_judged"].items())
            title = f":{'green' if ok else 'red'}[**{'CONSISTENT' if ok else 'INCONSISTENT'}**]  ·  " \
                    f"**{row['case']}**  ·  {headline}"
            with st.expander(title, icon=":material/check_circle:" if ok else ":material/cancel:", expanded=not ok):
                html(f'<div class="question">{ui.esc(reps[0].question or "-")}</div>')
                stats_line = []
                if row["same"]:
                    overlap = row["overlap"]
                    stats_line.append(ui.chip(f"{release.field_label(row['same'])}: {overlap:.0%} in common",
                                              "good-soft" if overlap >= spec.get("min_overlap", 1.0) else "bad-soft"))
                for name, value in row["passes"].items():
                    k, n = (int(x) for x in value.split("/"))
                    stats_line.append(ui.chip(f"{ui.label(name).lower()} passed {k} of {n}",
                                              "good-soft" if k == n else "bad-soft"))
                for name, why in row["not_judged"].items():
                    stats_line.append(ui.chip(f"{ui.label(name).lower()}: not judged ({friendly(why)})", "ghost"))
                for field, overlap in row["also"].items():
                    stats_line.append(ui.chip(f"{release.field_label(field)}: {overlap:.0%} in common", "ghost"))
                html(f'<div class="stat-line">{"".join(stats_line)}</div>')

                grid = ui.pages_by_run(reps)
                if grid:
                    html('<div class="card-label">Pages used in each run</div>')
                    html(ui.pages_grid_html(grid, len(reps)))
                    st.caption("anchor = the main page the answer is built on · expanded = related page added · "
                               "cited = referenced in the answer · used = in the evidence list only. "
                               "Highlighted rows changed between runs.")
                html('<div class="card-label" style="margin-top:14px">The answer in each run</div>')
                for tab, case in zip(st.tabs([f"Run {c.rep + 1}" for c in reps]), reps, strict=True):
                    with tab:
                        render_run(case)

# --- Trends ----------------------------------------------------------------------------------------

with trends_tab:
    history = [load(rid) for rid in reversed(by_pair[(agent, suite)][:20])]
    if len(history) < 2:
        st.info(f"Only one run of {agent}/{suite} so far. Trends appear from the second run on.")
    else:
        rows = []
        for number, past in enumerate(history, 1):
            s = ui.run_stats(past)
            when = pd.to_datetime(past.started_at)
            point = f"#{number} · {when:%d %b %H:%M}" + (f" · {past.build}" if past.build else "")
            rows.append({"run": point, "series": "Cases passing", "value": s["passed"] / max(s["cases"], 1)})
            for row in summarise([past]):
                if row["kind"] == "judge" and row["mean_score"] is not None:
                    rows.append({"run": point, "series": f"{ui.label(row['name'])} (mean score)",
                                 "value": row["mean_score"]})
        frame = pd.DataFrame(rows)
        st.markdown('<div class="section-title">Pass rate and judge scores, run by run</div>'
                    f'<div class="section-note">The last {len(history)} runs of {agent}/{suite}, oldest on the left.'
                    '</div>', unsafe_allow_html=True)
        st.altair_chart(alt.Chart(frame).mark_line(point=True, strokeWidth=2.5).encode(
            x=alt.X("run:N", sort=None, title=None, axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            color=alt.Color("series:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["run", "series", alt.Tooltip("value:Q", format=".2f")]).properties(height=340),
            width="stretch")
        st.dataframe(pd.DataFrame([{
            "run": p.run_id, "build": p.build, "mode": "offline" if p.offline else "live",
            "cases passing": f"{(s := ui.run_stats(p))['passed']}/{s['cases']}",
            "judges": ui.pct(s["judge_rate"]), "checks": ui.pct(s["check_rate"]), "errors": s["errors"],
        } for p in reversed(history)]), hide_index=True, width="stretch")

# --- Baseline --------------------------------------------------------------------------------------

with baseline_tab:
    path = baseline_path(run.agent, run.suite)
    if not path.is_file():
        st.info(f"No baseline for {run.agent}/{run.suite} yet. Create one from a stable build:\n\n"
                f"`make baseline AGENT={run.agent} SUITE={run.suite} BUILD=<stable build> REPS=5`")
    else:
        passed, rows, baseline = compare(run)
        regressions = [r for r in rows if r["status"] in ("regression", "missing")]
        word = "No regressions" if passed else f"{len(regressions)} regression{'s' * (len(regressions) != 1)}"
        html(f'<div class="hero"><div><div class="hero-title">{ui.esc(word)}</div><div class="hero-sub">'
             f'build {ui.esc(run.build or "?")} against baseline build {ui.esc(baseline.get("build") or "?")}'
             f'</div></div><div class="verdict"><span class="verdict-word {"good" if passed else "bad"}">'
             f'{"PASS" if passed else "FAIL"}</span></div></div>')
        order = {"regression": 0, "missing": 1, "improved": 2, "new": 3, "ok": 4}
        st.dataframe(pd.DataFrame([{
            "status": r["status"].upper(), "case :: result": r["result"],
            "baseline pass rate": (r["baseline"] or {}).get("pass_rate"),
            "current pass rate": (r["current"] or {}).get("pass_rate"),
            "baseline score": (r["baseline"] or {}).get("mean_score"),
            "current score": (r["current"] or {}).get("mean_score"), "note": r["note"],
        } for r in sorted(rows, key=lambda r: order.get(r["status"], 9))]), hide_index=True, width="stretch",
            column_config={k: st.column_config.ProgressColumn(k, min_value=0, max_value=1, format="percent")
                           for k in ("baseline pass rate", "current pass rate")})
        st.caption("This compares the selected run with the baseline. `make verdict` saves the comparison as its "
                   "own run — pick the ⚖ VERDICT run in the sidebar for the release view (both builds side by side).")
