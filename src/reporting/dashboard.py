"""
Results dashboard: `make dashboard` (runs `streamlit run src/reporting/dashboard.py`).

Read-only: it reads outputs/runs/*/results.json and baselines/ — nothing else. Four tabs:
  Overview    the run at a glance: pass rates, every judge and check across the run, where cases fail
  Test cases  one accordion per case: question, agent answer, expected answer and the pages behind it
              on the left; LLM judges and deterministic checks, kept apart, on the right; errors
              explained (what failed, the message, how to fix) at the top
  Trends      the same agent + suite over its recent runs
  Baseline    this run against the agent/suite baseline (same logic as `make verdict`)

The pieces that aren't Streamlit calls (error explanations, HTML blocks) are in dashboard_parts.py.
"""

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
from src.reporting.summary import summarise  # noqa: E402
from src.verdict.baseline import baseline_path  # noqa: E402
from src.verdict.compare import compare  # noqa: E402

st.set_page_config(page_title="Agent evals", page_icon=":material/fact_check:", layout="wide")

PAGE_SIZE = 25
COLORS = {PASS: "#16a34a", FAIL: "#dc2626", ERROR: "#d97706", SKIP: "#94a3b8"}

LIGHT = """--surface:#ffffff; --surface-2:#f8fafc; --border:rgba(15,23,42,.10); --ink:#0f172a; --ink-2:#475569;
  --muted:#94a3b8; --good:#16a34a; --bad:#dc2626; --warn:#d97706; --accent:#4f46e5; --track:#e2e8f0;
  --good-wash:rgba(22,163,74,.10); --bad-wash:rgba(220,38,38,.09); --warn-wash:rgba(217,119,6,.11);
  --accent-wash:rgba(79,70,229,.10); --hero:linear-gradient(120deg,#eef2ff 0%,#f8fafc 60%,#ecfdf5 100%);"""
DARK = """--surface:#15171c; --surface-2:#1b1e24; --border:rgba(255,255,255,.10); --ink:#f1f5f9; --ink-2:#cbd5e1;
  --muted:#7c8799; --good:#22c55e; --bad:#f87171; --warn:#fbbf24; --accent:#818cf8; --track:#2a2f38;
  --good-wash:rgba(34,197,94,.14); --bad-wash:rgba(248,113,113,.14); --warn-wash:rgba(251,191,36,.14);
  --accent-wash:rgba(129,140,248,.16); --hero:linear-gradient(120deg,#1e1b4b 0%,#15171c 60%,#052e16 100%);"""
CSS = """
<style>
:root { %s }
.block-container { padding-top: 2rem; }
.hero { background:var(--hero); border:1px solid var(--border); border-radius:18px; padding:22px 26px;
  display:flex; align-items:center; gap:24px; flex-wrap:wrap; margin-bottom:18px; }
.hero-title { font-size:26px; font-weight:750; color:var(--ink); letter-spacing:-.01em; }
.hero-sub { color:var(--ink-2); font-size:13px; margin-top:6px; display:flex; gap:6px; flex-wrap:wrap; }
.verdict { margin-left:auto; text-align:right; }
.verdict-word { font-size:15px; font-weight:750; padding:6px 14px; border-radius:999px; display:inline-block; }
.verdict-word.good { background:var(--good-wash); color:var(--good); }
.verdict-word.bad { background:var(--bad-wash); color:var(--bad); }
.verdict-word.warn { background:var(--warn-wash); color:var(--warn); }
.verdict-note { color:var(--ink-2); font-size:12px; margin-top:6px; }
.kpis { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:4px 0 18px; }
@media (max-width:1100px) { .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.kpi { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:14px 16px;
  border-top:3px solid var(--track); }
.kpi.good { border-top-color:var(--good); } .kpi.bad { border-top-color:var(--bad); }
.kpi.warn { border-top-color:var(--warn); } .kpi.accent { border-top-color:var(--accent); }
.kpi-label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; font-weight:650; }
.kpi-value { font-size:28px; font-weight:750; color:var(--ink); font-variant-numeric:tabular-nums; margin-top:2px; }
.kpi.good .kpi-value { color:var(--good); } .kpi.bad .kpi-value { color:var(--bad); }
.kpi.warn .kpi-value { color:var(--warn); }
.kpi-sub { font-size:12px; color:var(--ink-2); margin-top:2px; min-height:16px; }
.card-label { font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
  font-weight:700; margin-bottom:6px; display:flex; align-items:center; gap:8px; }
.card-label .count { margin-left:auto; text-transform:none; letter-spacing:0; font-weight:600; color:var(--ink-2); }
.section-title { font-size:15px; font-weight:700; color:var(--ink); margin:6px 0 2px; }
.section-note { font-size:12px; color:var(--ink-2); margin-bottom:10px; }
.chip { display:inline-flex; align-items:center; padding:1px 9px; border-radius:999px; font-size:11.5px;
  font-weight:600; white-space:nowrap; border:1px solid var(--border); background:var(--surface-2);
  color:var(--ink-2); margin:2px 4px 2px 0; }
.chip.ghost { background:transparent; color:var(--muted); }
.chip.accent { background:var(--accent-wash); color:var(--accent); border-color:transparent; }
.chip.good { background:var(--good); color:#fff; border-color:transparent; }
.chip.bad { background:var(--bad); color:#fff; border-color:transparent; }
.chip.warn { background:var(--warn); color:#fff; border-color:transparent; }
.chip.good-soft { background:var(--good-wash); color:var(--good); border-color:transparent; }
.chip.bad-soft { background:var(--bad-wash); color:var(--bad); border-color:transparent; }
.chip.warn-soft { background:var(--warn-wash); color:var(--warn); border-color:transparent; }
.chips { display:flex; flex-wrap:wrap; margin-top:4px; }
.muted { color:var(--muted); } .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.row-top { display:flex; align-items:baseline; gap:8px; }
.row-name { font-size:13.5px; font-weight:650; color:var(--ink); }
.row-reason { font-size:12.5px; color:var(--ink-2); margin-top:3px; line-height:1.45; }
.score { margin-left:auto; font-size:13px; font-weight:750; font-variant-numeric:tabular-nums; white-space:nowrap; }
.score.good { color:var(--good); } .score.bad { color:var(--bad); } .score.warn { color:var(--warn); }
.score.muted { color:var(--muted); font-weight:600; }
.bar { position:relative; height:7px; border-radius:4px; background:var(--track); margin:7px 0 4px; }
.bar-fill { position:absolute; left:0; top:0; height:100%%; border-radius:4px; background:var(--muted); }
.bar-fill.good { background:var(--good); } .bar-fill.bad { background:var(--bad); }
.bar-fill.warn { background:var(--warn); }
.bar-marker { position:absolute; top:-3px; width:2px; height:13px; background:var(--ink); opacity:.55;
  border-radius:1px; }
.judge, .sb-row { padding:10px 0; border-top:1px solid var(--border); }
.judge:first-child, .sb-row:first-child { border-top:none; padding-top:2px; }
.check { display:flex; gap:9px; padding:6px 0; align-items:flex-start; }
.icon { width:18px; height:18px; border-radius:50%%; display:inline-flex; align-items:center; justify-content:center;
  font-size:11px; font-weight:800; flex-shrink:0; margin-top:1px; }
.icon.good { background:var(--good-wash); color:var(--good); }
.icon.bad { background:var(--bad-wash); color:var(--bad); }
.icon.warn { background:var(--warn-wash); color:var(--warn); }
.icon.muted { background:var(--surface-2); color:var(--muted); }
.group { padding:8px 0 6px; border-top:1px solid var(--border); }
.group:first-child { border-top:none; padding-top:0; }
.group-head { display:flex; justify-content:space-between; font-size:12px; font-weight:700; color:var(--ink);
  text-transform:uppercase; letter-spacing:.05em; margin-bottom:2px; }
details.skips summary { cursor:pointer; font-size:12px; color:var(--muted); margin-top:4px; }
.problem { border:1px solid var(--warn); background:var(--warn-wash); border-radius:12px; padding:12px 14px;
  margin-bottom:10px; }
.problem-title { font-weight:750; color:var(--ink); font-size:14px; }
.problem-reason { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:var(--ink);
  background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:8px 10px; margin:8px 0;
  white-space:pre-wrap; word-break:break-word; }
.problem-hint { font-size:12.5px; color:var(--ink-2); }
.question { font-size:16px; font-weight:600; color:var(--ink); line-height:1.45; }
.page { padding:7px 0; border-top:1px solid var(--border); font-size:13px; }
.page:first-of-type { border-top:none; }
details.page summary { cursor:pointer; }
.page-title { font-weight:600; color:var(--ink); }
.page-text { white-space:pre-wrap; font-size:12.5px; color:var(--ink-2); background:var(--surface-2);
  border-radius:8px; padding:10px 12px; margin-top:6px; max-height:320px; overflow:auto; }
.note { font-size:12.5px; color:var(--muted); font-style:italic; }
.missed { font-size:12.5px; color:var(--bad); margin-top:6px; }
</style>
"""


def theme_css() -> str:
    dark = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
    return CSS % (DARK if dark else LIGHT)


st.markdown(theme_css(), unsafe_allow_html=True)


def html(markup: str, target=st) -> None:
    target.markdown(markup, unsafe_allow_html=True)


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
    return f"{stamp} · {passed}/{len(run.cases)} passed{build}"


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
                          help="Newest first. Each `make run` is one run.")
    st.divider()
    st.markdown("**Filter test cases**")
    status_filter = st.pills("Status", ["Fail", "Error", "Pass"], selection_mode="multi",
                             default=["Fail", "Error", "Pass"], label_visibility="collapsed")
    search = st.text_input("Search", placeholder="case id, question or answer text",
                           label_visibility="collapsed")
    st.caption("Results are read from outputs/runs. Refresh the page after a new run.")

run = load(run_id)
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

overview_tab, cases_tab, trends_tab, baseline_tab = st.tabs([
    ":material/dashboard: Overview", f":material/list_alt: Test cases ({len(run.cases)})",
    ":material/trending_up: Trends", ":material/compare_arrows: Baseline"])

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
            st.caption("Targets are pass rates across the whole run (agent.yaml `targets:`), not per-case scores. "
                       "A target with no data counts as missed.")
    if run.reps > 1:
        rows_c = release.consistency(run)
        if rows_c:
            with st.container(border=True):
                ok = sum(r["consistent"] for r in rows_c)
                html(f'<div class="card-label">Consistency over {run.reps} repetitions<span class="count">'
                     f'{ui.chip(f"{ok}/{len(rows_c)} cases consistent", "good" if ok == len(rows_c) else "bad")}'
                     '</span></div>')
                st.dataframe(pd.DataFrame([{
                    "case": r["case"], "consistent": "yes" if r["consistent"] else "NO",
                    "same sources (overlap)":
                        None if r["evidence_overlap"] is None else round(r["evidence_overlap"], 2),
                    **{f"{k} passed": v for k, v in r["passes"].items()}, "why not": r["why"],
                } for r in rows_c]), hide_index=True, width="stretch")
                st.caption("A case is consistent only if its source pages are the same in every repetition and the "
                           "results in agent.yaml `consistency: all_pass` passed every time (HIVE-6165).")

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

# --- Test cases ------------------------------------------------------------------------------------


def matches(case: CaseResult) -> bool:
    wanted = {s.lower() for s in (status_filter or [])}
    if case.status not in wanted:
        return False
    text = search.strip().casefold()
    return not text or any(text in (v or "").casefold() for v in (case.case_id, case.question, case.answer))


def case_header(case: CaseResult) -> tuple[str, str]:
    judges, groups = ui.split(case)
    checks = [r for g in groups.values() for r in g]
    color = {PASS: "green", FAIL: "red", ERROR: "orange"}[case.status]
    icon = {PASS: ":material/check_circle:", FAIL: ":material/cancel:", ERROR: ":material/error:"}[case.status]
    question = ui.short(case.question or case.description or "", 80)
    bits = [f":{color}[**{case.status.upper()}**]", f"**{case.case_id}**"]
    if run.reps > 1:
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


def render_right(case: CaseResult, col) -> None:
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
        elif run.checks == []:
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


with cases_tab:
    shown = [c for c in run.cases if matches(c)]
    shown.sort(key=lambda c: {ERROR: 0, FAIL: 1, PASS: 2}[c.status])
    top = st.columns([3, 1])
    top[0].caption(f"{len(shown)} of {len(run.cases)} cases · problems first · use the sidebar to filter. "
                   "Left: what was asked and answered. Right: LLM judges, then deterministic checks.")
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    page = top[1].number_input("Page", 1, pages, 1, label_visibility="collapsed") if pages > 1 else 1
    if not shown:
        st.info("No case matches the filters.")
    for case in shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        title, icon = case_header(case)
        with st.expander(title, icon=icon, expanded=len(shown) == 1):
            for problem in ui.problems(case):
                html(ui.problem_html(problem))
            left, right = st.columns([1.15, 1], gap="medium")
            render_left(case, left)
            render_right(case, right)
            render_debug(case)

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
