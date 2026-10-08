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
from src.reporting.dashboard_cases import render_case_list  # noqa: E402
from src.reporting.dashboard_style import apply_theme, html  # noqa: E402
from src.reporting.dashboard_verdict import render_verdict  # noqa: E402
from src.reporting.summary import summarise  # noqa: E402
from src.verdict.baseline import baseline_path  # noqa: E402
from src.verdict.compare import compare  # noqa: E402

st.set_page_config(page_title="Agent evals", page_icon=":material/fact_check:", layout="wide")

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

# --- the selected run -------------------------------------------------------------------------------

run = load(run_id)

verdict = vv.load(run)
if verdict is not None:
    render_verdict(verdict, status_filter, search)
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
    render_case_list(run, "run", status_filter, search)

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
