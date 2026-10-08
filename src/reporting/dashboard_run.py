"""
The page for an ordinary run (one saved by `make run` or `make baseline`).

Layout, top to bottom:
  a header   agent name, suite, build, and one line saying how the run went
  tabs       Overview, Test cases, (Consistency, only when REPS > 1), Trends, Baseline

Each tab is one small function below. The Test cases tab lives in dashboard_cases.py and the Consistency
tab in dashboard_consistency.py.

Used by: dashboard.py.
"""

import altair as alt
import pandas as pd
import streamlit as st

from src.core.results import ERROR, FAIL, PASS, SKIP, Run
from src.reporting import dashboard_parts as ui
from src.reporting import release
from src.reporting.dashboard_cases import render_case_list
from src.reporting.dashboard_consistency import show_consistency_tab
from src.reporting.dashboard_data import load
from src.reporting.dashboard_style import html
from src.reporting.summary import summarise
from src.verdict.baseline import baseline_path
from src.verdict.compare import compare

# The colour of each status in the "every case x every result" chart.
COLORS = {PASS: "#16a34a", FAIL: "#dc2626", ERROR: "#d97706", SKIP: "#94a3b8"}


def render_run_page(run: Run, same_suite_ids: list[str], status_filter: list[str], search: str) -> None:
    """Draw the whole page for one run.

    same_suite_ids: the ids of every run of this agent and suite, newest first (used by the Trends tab).
    status_filter, search: the filters chosen in the sidebar (used by the Test cases tab).
    """
    stats = ui.run_stats(run)           # the totals: cases passed, judge pass rate, latency ...
    summary = summarise([run])          # one row per judge / check, with its pass rate

    show_header(run, stats)

    # The Consistency tab only exists when every case was run more than once.
    consistency_rows = release.consistency(run) if run.reps > 1 else []
    tab_names = [":material/dashboard: Overview", f":material/list_alt: Test cases ({len(run.cases)})",
                 ":material/trending_up: Trends", ":material/compare_arrows: Baseline"]
    if consistency_rows:
        tab_names.insert(2, ":material/repeat: Consistency")
    tabs = st.tabs(tab_names)
    overview_tab, cases_tab = tabs[0], tabs[1]
    consistency_tab = tabs[2] if consistency_rows else None
    trends_tab, baseline_tab = tabs[-2], tabs[-1]

    with overview_tab:
        show_overview(run, stats, summary, consistency_rows)
    with cases_tab:
        render_case_list(run, "run", status_filter, search)
    if consistency_tab is not None:
        with consistency_tab:
            show_consistency_tab(run, consistency_rows)
    with trends_tab:
        show_trends(run, same_suite_ids)
    with baseline_tab:
        show_baseline(run)


# --- header --------------------------------------------------------------------------------------

def show_header(run: Run, stats: dict) -> None:
    """The big box at the top: agent name, small chips (suite, build ...) and the one-line result."""
    mode = "offline replay" if run.offline else "live agent"
    sub = "".join(ui.chip(x, k) for x, k in [
        (run.suite, "accent"), (f"build {run.build}" if run.build else "no build label", "plain"),
        (mode, "plain"), (f"{run.reps} rep{'s' * (run.reps > 1)}", "plain"),
        (pd.to_datetime(run.started_at).strftime("%d %b %Y, %H:%M") if run.started_at else "", "ghost"),
        (run.run_id, "ghost")] if x)

    # The one-line result: errors first, then failures, otherwise all good.
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


# --- Overview tab --------------------------------------------------------------------------------

def show_overview(run: Run, stats: dict, summary: list[dict], consistency_rows: list[dict]) -> None:
    """The run at a glance: numbers, release targets, consistency, scoreboards, what needs attention."""
    show_kpis(stats)
    show_targets(run)
    if consistency_rows:
        show_consistency_card(run, consistency_rows)

    # Two boxes side by side: LLM judges on the left, deterministic checks on the right.
    left, right = st.columns(2, gap="large")
    with left.container(border=True):
        html('<div class="card-label">LLM judges<span class="count">pass rate across cases</span></div>')
        html(ui.scoreboard_html(summary, "judge"))
    with right.container(border=True):
        html('<div class="card-label">Deterministic checks<span class="count">pass rate across cases'
             '</span></div>')
        html(ui.check_scoreboard_html(summary))

    show_needs_attention(run)
    show_heatmap(run)


def show_kpis(stats: dict) -> None:
    """The row of five big numbers."""
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


def show_targets(run: Run) -> None:
    """The release targets from agent.yaml, with how many were missed. Nothing is drawn if there are none."""
    gate_ok, target_rows = release.gate(run)
    if not target_rows:
        return
    with st.container(border=True):
        missed = sum(r["met"] is False for r in target_rows)
        status = ui.chip("all targets met", "good") if gate_ok else ui.chip(f"{missed} target(s) missed", "bad")
        html(f'<div class="card-label">Release targets<span class="count">{status}</span></div>')
        html(ui.targets_html(target_rows))


def show_consistency_card(run: Run, consistency_rows: list[dict]) -> None:
    """A short summary of the Consistency tab: how many cases agreed with themselves."""
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


def show_needs_attention(run: Run) -> None:
    """A table of every case that did not pass, with the first reason."""
    attention = [c for c in run.cases if c.status != PASS]
    st.markdown('<div class="section-title">Needs attention</div>'
                '<div class="section-note">Every case that failed or could not be evaluated, with the first reason.'
                ' Open it in the Test cases tab for the full picture.</div>', unsafe_allow_html=True)
    if not attention:
        st.success("Nothing to look at: every case passed.", icon=":material/celebration:")
        return
    st.dataframe(pd.DataFrame([{
        "status": c.status.upper(), "case": c.case_id + (f" · rep {c.rep + 1}" if run.reps > 1 else ""),
        "question": c.question, "why": ui.first_issue(c),
        "judges": ui.ran(ui.tally(ui.split(c)[0])),
        "checks": ui.ran(ui.tally([r for g in ui.split(c)[1].values() for r in g])),
    } for c in attention]), hide_index=True, width="stretch",
        column_config={"question": st.column_config.TextColumn(width="large"),
                       "why": st.column_config.TextColumn(width="large")})


def show_heatmap(run: Run) -> None:
    """A grid of coloured squares: one row per case, one column per judge / check."""
    cells = [{"case": c.case_id + (f" r{c.rep + 1}" if run.reps > 1 else ""), "result": ui.label(r.name),
              "kind": "LLM judge" if r.kind == "judge" else "check", "status": r.status,
              "detail": r.reason or ("passed" if r.status == PASS else "")}
             for c in run.cases for r in c.results if not ui.is_setup(r)]
    for c in run.cases:                        # a first column: could the case be evaluated at all?
        trouble = ui.problems(c)
        cells.append({"case": c.case_id + (f" r{c.rep + 1}" if run.reps > 1 else ""), "result": "Agent & setup",
                      "kind": "setup", "status": ERROR if trouble else PASS,
                      "detail": trouble[0]["title"] if trouble else "the agent answered"})
    if not cells:
        return
    st.markdown('<div class="section-title">Every case × every result</div>'
                '<div class="section-note">Columns: could it be evaluated, then LLM judges, then checks. '
                'Hover a cell for why.'
                '</div>', unsafe_allow_html=True)
    frame = pd.DataFrame(cells)
    rank = {"setup": 0, "LLM judge": 1, "check": 2}     # column order: setup, then judges, then checks
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


# --- Trends tab ----------------------------------------------------------------------------------

def show_trends(run: Run, same_suite_ids: list[str]) -> None:
    """The same agent and suite over its last 20 runs: a line chart and a table."""
    # same_suite_ids is newest first; the chart reads left to right, so reverse it (oldest first).
    history = [load(rid) for rid in reversed(same_suite_ids[:20])]
    if len(history) < 2:
        st.info(f"Only one run of {run.agent}/{run.suite} so far. Trends appear from the second run on.")
        return

    # One point per run for "cases passing", and one per run for each judge's mean score.
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
                f'<div class="section-note">The last {len(history)} runs of {run.agent}/{run.suite}, '
                'oldest on the left.</div>', unsafe_allow_html=True)
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


# --- Baseline tab --------------------------------------------------------------------------------

def show_baseline(run: Run) -> None:
    """This run against the saved baseline (the same comparison `make verdict` makes)."""
    path = baseline_path(run.agent, run.suite)
    if not path.is_file():
        st.info(f"No baseline for {run.agent}/{run.suite} yet. Create one from a stable build:\n\n"
                f"`make baseline AGENT={run.agent} SUITE={run.suite} BUILD=<stable build> REPS=5`")
        return

    passed, rows, baseline = compare(run)
    regressions = [r for r in rows if r["status"] in ("regression", "missing")]
    word = "No regressions" if passed else f"{len(regressions)} regression{'s' * (len(regressions) != 1)}"
    html(f'<div class="hero"><div><div class="hero-title">{ui.esc(word)}</div><div class="hero-sub">'
         f'build {ui.esc(run.build or "?")} against baseline build {ui.esc(baseline.get("build") or "?")}'
         f'</div></div><div class="verdict"><span class="verdict-word {"good" if passed else "bad"}">'
         f'{"PASS" if passed else "FAIL"}</span></div></div>')
    order = {"regression": 0, "missing": 1, "improved": 2, "new": 3, "ok": 4}     # worst first
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
