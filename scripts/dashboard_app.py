"""
Streamlit dashboard for evaluation results.

Two views (sidebar toggle) — neither replaces the other:
  - By stage: one card per stage × case (existing stage-wise debugging)
  - By test case (e2e): one card per case with stages nested inside

Reads timestamped JSON under outputs/dashboard/runs/<stamp>/ (LATEST pointer).
Defaults to the newest run; pick older runs from the sidebar.

Files per run:
  - <agent>/<eval>__<id>.json  → CaseEvaluationResult
  - <agent>/e2e__<id>.json     → E2ECaseResult (kind=e2e)

    streamlit run scripts/dashboard_app.py
"""

import html
import json
import sys
from pathlib import Path

# `streamlit run` execs this file with only its own directory (scripts/) on
# sys.path, unlike `python -m`, which puts the repo root there - add it
# explicitly so `src` is importable regardless of how this is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.models.evaluation_result import CaseEvaluationResult, E2ECaseResult
from src.reporting.persist import DEFAULT_DASHBOARD_ROOT, list_runs, resolve_latest_run

st.set_page_config(page_title="Agent Evaluation Dashboard", page_icon="🧪", layout="wide")

CSS = """
<style>
:root {
  --surface: #fcfcfb; --surface-2: #ffffff; --page: #f9f9f7;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --border: rgba(11,11,11,0.10); --track: #e1e0d9;
  --good: #0ca30c; --critical: #d03b3b;
  --good-wash: rgba(12,163,12,0.10); --critical-wash: rgba(208,59,59,0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1f1f1e; --surface-2: #262625; --page: #0d0d0d;
    --ink: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --border: rgba(255,255,255,0.14); --track: #383835;
    --good: #0ca30c; --critical: #e66767;
    --good-wash: rgba(12,163,12,0.16); --critical-wash: rgba(230,103,103,0.18);
  }
}
html, body, [class*="css"] { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }

.stat-row { display:flex; gap:14px; flex-wrap:wrap; margin: 4px 0 22px 0; }
.stat-tile { flex:1; min-width:150px; background:var(--surface); border:1px solid var(--border);
  border-radius:14px; padding:16px 18px; }
.stat-tile .label { font-size:12px; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; }
.stat-tile .value { font-size:28px; font-weight:700; color:var(--ink); font-variant-numeric: tabular-nums; margin-top:2px; }
.stat-tile .value.good { color: var(--good); }
.stat-tile .value.critical { color: var(--critical); }

.case-card { border:1px solid var(--border); border-radius:16px; background:var(--surface);
  padding:20px 22px; margin-bottom:20px; }
.case-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.case-id { font-size:17px; font-weight:700; color:var(--ink); margin-right:2px; }
.pill { display:inline-flex; align-items:center; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }
.pill.agent, .pill.stage { background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border); }
.pill.status-good { background:var(--good-wash); color:var(--good); }
.pill.status-critical { background:var(--critical-wash); color:var(--critical); }
.case-latency { color:var(--ink-muted); font-size:12px; margin-left:auto; font-variant-numeric: tabular-nums; }
.case-question { color:var(--ink-2); font-size:14px; margin: 8px 0 4px 0; font-style: italic; }

.case-body-grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top:14px; align-items:stretch; }
@media (max-width: 900px) { .case-body-grid { grid-template-columns: 1fr; } }

.check-card { border:1px solid var(--border); border-radius:12px; background:var(--surface-2); padding:14px 16px; height:100%; }
.check-card-title { font-size:12px; font-weight:700; color:var(--ink); text-transform:uppercase; letter-spacing:.04em; }
.check-card-sub { font-size:12px; color:var(--ink-muted); margin-bottom:6px; }

.check-row { display:flex; align-items:flex-start; gap:8px; padding:9px 0; border-top:1px solid var(--border); }
.check-row:first-of-type { border-top:none; }
.check-icon { font-size:13px; width:16px; text-align:center; flex-shrink:0; margin-top:2px; font-weight:700; }
.check-icon.good { color:var(--good); }
.check-icon.critical { color:var(--critical); }
.check-body { flex:1; min-width:0; }
.check-name { font-size:13px; font-weight:600; color:var(--ink); }
.check-reason { font-size:12px; color:var(--ink-2); margin-top:2px; line-height:1.4; }

.meter-row { padding:9px 0; border-top:1px solid var(--border); }
.meter-row:first-of-type { border-top:none; }
.meter-top { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.meter-score { font-size:12px; font-variant-numeric: tabular-nums; font-weight:700; white-space:nowrap; }
.meter-score.good { color: var(--good); }
.meter-score.critical { color: var(--critical); }
.meter-score .thresh { color:var(--ink-muted); font-weight:400; }
.meter-track { position:relative; height:6px; border-radius:4px; background:var(--track); margin:6px 0 5px 0; }
.meter-fill { position:absolute; top:0; left:0; height:100%; border-radius:4px; }
.meter-fill.good { background:var(--good); }
.meter-fill.critical { background:var(--critical); }
.meter-threshold { position:absolute; top:-2px; width:2px; height:10px; background:var(--ink-muted); border-radius:1px; }

.stage-summary { display:flex; gap:8px; flex-wrap:wrap; margin: 10px 0 4px 0; }
.stage-chip { font-size:12px; padding:4px 10px; border-radius:8px; border:1px solid var(--border);
  background:var(--surface-2); color:var(--ink-2); }
.stage-chip.good { border-color: var(--good); color: var(--good); background: var(--good-wash); }
.stage-chip.critical { border-color: var(--critical); color: var(--critical); background: var(--critical-wash); }

.empty-card { font-size:12px; color:var(--ink-muted); padding:8px 0; }
.empty-state { text-align:center; padding:70px 20px; color:var(--ink-muted); }
.empty-state code { background:var(--surface-2); padding:2px 6px; border-radius:6px; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _load_all(output_dir: str) -> tuple[list[CaseEvaluationResult], list[E2ECaseResult]]:
    root = Path(output_dir)
    if not root.exists():
        return [], []
    stage_results: list[CaseEvaluationResult] = []
    e2e_results: list[E2ECaseResult] = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and data.get("kind") == "e2e":
            try:
                e2e_results.append(E2ECaseResult.model_validate(data))
            except Exception:
                continue
        else:
            try:
                stage_results.append(CaseEvaluationResult.model_validate(data))
            except Exception:
                continue
    return stage_results, e2e_results


def _pct(numerator: int, denominator: int) -> str:
    return f"{(100 * numerator / denominator):.0f}%" if denominator else "–"


def _status_pill(passed: bool) -> str:
    cls = "status-good" if passed else "status-critical"
    label = "PASS" if passed else "FAIL"
    return f'<span class="pill {cls}">{label}</span>'


def _det_row_html(check) -> str:
    cls = "good" if check.passed else "critical"
    icon = "✓" if check.passed else "✗"
    name = _esc(check.name.replace("_", " ").title())
    reason = f'<div class="check-reason">{_esc(check.reason)}</div>' if check.reason else ""
    return (
        f'<div class="check-row"><div class="check-icon {cls}">{icon}</div>'
        f'<div class="check-body"><div class="check-name">{name}</div>{reason}</div></div>'
    )


def _judge_row_html(metric) -> str:
    cls = "good" if metric.passed else "critical"
    score = max(0.0, min(1.0, metric.score))
    threshold = max(0.0, min(1.0, metric.threshold))
    name = _esc(metric.name.replace("_", " ").title())
    reason = f'<div class="check-reason">{_esc(metric.reason)}</div>' if metric.reason else ""
    return (
        f'<div class="meter-row">'
        f'<div class="meter-top"><span class="check-name">{name}</span>'
        f'<span class="meter-score {cls}">{metric.score:.2f} '
        f'<span class="thresh">/ {metric.threshold:.2f}</span></span></div>'
        f'<div class="meter-track">'
        f'<div class="meter-fill {cls}" style="width:{score * 100:.0f}%"></div>'
        f'<div class="meter-threshold" style="left:{threshold * 100:.0f}%"></div>'
        f"</div>{reason}</div>"
    )


def _check_card_html(title: str, passed_n: int, total_n: int, empty_label: str, rows_html: str) -> str:
    subtitle = f"{passed_n}/{total_n} passed" if total_n else empty_label
    if not rows_html:
        rows_html = f'<div class="empty-card">{_esc(empty_label)}</div>'
    return (
        f'<div class="check-card"><div class="check-card-title">{_esc(title)}</div>'
        f'<div class="check-card-sub">{_esc(subtitle)}</div>{rows_html}</div>'
    )


def _stat_tiles(tiles: list[tuple[str, str, str]]) -> None:
    tiles_html = ['<div class="stat-row">']
    for label, value, cls in tiles:
        tiles_html.append(
            f'<div class="stat-tile"><div class="label">{_esc(label)}</div>'
            f'<div class="value {cls}">{_esc(value)}</div></div>'
        )
    tiles_html.append("</div>")
    st.markdown("".join(tiles_html), unsafe_allow_html=True)


def _render_stage_body(r: CaseEvaluationResult, *, key_prefix: str) -> None:
    """Shared det/judge panels + answer/context/trace expanders."""
    det_rows = "".join(_det_row_html(c) for c in r.deterministic_results)
    judge_rows = "".join(_judge_row_html(m) for m in r.metric_results)
    det_passed_n = sum(c.passed for c in r.deterministic_results)
    judge_passed_n = sum(m.passed for m in r.metric_results)
    latency_html = f'<span class="case-latency">{r.latency_ms / 1000:.1f}s</span>' if r.latency_ms else ""
    question_html = f'<div class="case-question">{_esc(r.question)}</div>' if r.question else ""

    card_html = f"""
    <div class="case-card">
      <div class="case-head">
        <span class="case-id">{_esc(r.test_case_id)}</span>
        <span class="pill agent">{_esc(r.agent_name or "unknown agent")}</span>
        <span class="pill stage">{_esc(r.eval_name)}</span>
        {_status_pill(r.passed)}
        {latency_html}
      </div>
      {question_html}
      <div class="case-body-grid">
        {_check_card_html("Deterministic Checks", det_passed_n, len(r.deterministic_results), "No deterministic checks", det_rows)}
        {_check_card_html("Non-Deterministic Checks", judge_passed_n, len(r.metric_results), "No judge metrics ran", judge_rows)}
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    with st.expander("Agent answer"):
        st.markdown(r.answer or "_(empty)_")

    with st.expander("Retrieved context"):
        if r.context:
            for i, ctx in enumerate(r.context, start=1):
                st.text_area(
                    f"Context {i}",
                    ctx,
                    height=120,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"{key_prefix}_ctx_{r.agent_name}_{r.eval_name}_{r.test_case_id}_{i}",
                )
        else:
            st.caption("No retrieved context recorded.")

    with st.expander("Agent trace"):
        st.json(r.model_dump())


def _render_stage_view(filtered: list[CaseEvaluationResult], show_eval: bool) -> None:
    total = len(filtered)
    passed = sum(r.passed for r in filtered)
    det_total = sum(len(r.deterministic_results) for r in filtered)
    det_passed = sum(sum(c.passed for c in r.deterministic_results) for r in filtered)
    judge_total = sum(len(r.metric_results) for r in filtered)
    judge_passed = sum(sum(m.passed for m in r.metric_results) for r in filtered)
    latencies = [r.latency_ms for r in filtered if r.latency_ms]
    avg_latency_s = (sum(latencies) / len(latencies) / 1000) if latencies else None

    _stat_tiles([
        ("Test cases", str(total), ""),
        ("Overall pass rate", _pct(passed, total), "good" if passed == total else "critical"),
        ("Deterministic checks", _pct(det_passed, det_total), "good" if det_passed == det_total else "critical"),
        ("Judge checks", _pct(judge_passed, judge_total), "good" if judge_total and judge_passed == judge_total else ("" if not judge_total else "critical")),
        ("Avg latency", f"{avg_latency_s:.1f}s" if avg_latency_s is not None else "–", ""),
    ])

    for r in sorted(filtered, key=lambda r: (r.test_case_id, r.eval_name)):
        status_icon = "✅" if r.passed else "❌"
        label_bits = [f"**{r.test_case_id}**", r.agent_name or "unknown agent"]
        if show_eval:
            label_bits.append(r.eval_name)
        if r.latency_ms:
            label_bits.append(f"{r.latency_ms / 1000:.1f}s")
        label = f"{status_icon}  " + "  ·  ".join(label_bits)

        with st.expander(label, expanded=False):
            _render_stage_body(r, key_prefix="stage")


def _render_e2e_view(filtered: list[E2ECaseResult]) -> None:
    total = len(filtered)
    passed = sum(r.passed for r in filtered)
    stage_rows = [s for r in filtered for s in r.stages]
    det_total = sum(len(s.deterministic_results) for s in stage_rows)
    det_passed = sum(sum(c.passed for c in s.deterministic_results) for s in stage_rows)
    judge_total = sum(len(s.metric_results) for s in stage_rows)
    judge_passed = sum(sum(m.passed for m in s.metric_results) for s in stage_rows)
    latencies = [r.latency_ms for r in filtered if r.latency_ms]
    avg_latency_s = (sum(latencies) / len(latencies) / 1000) if latencies else None

    _stat_tiles([
        ("Test cases", str(total), ""),
        ("E2E pass rate", _pct(passed, total), "good" if passed == total else "critical"),
        ("Deterministic checks", _pct(det_passed, det_total), "good" if det_passed == det_total else "critical"),
        ("Judge checks", _pct(judge_passed, judge_total), "good" if judge_total and judge_passed == judge_total else ("" if not judge_total else "critical")),
        ("Avg latency", f"{avg_latency_s:.1f}s" if avg_latency_s is not None else "–", ""),
    ])

    for r in sorted(filtered, key=lambda r: r.test_case_id):
        status_icon = "✅" if r.passed else "❌"
        n_stages = len(r.stages)
        stages_ok = sum(1 for s in r.stages if s.deterministic_passed)
        label_bits = [
            f"**{r.test_case_id}**",
            r.agent_name or "unknown agent",
            f"{stages_ok}/{n_stages} stages",
        ]
        if r.latency_ms:
            label_bits.append(f"{r.latency_ms / 1000:.1f}s")
        label = f"{status_icon}  " + "  ·  ".join(label_bits)

        with st.expander(label, expanded=False):
            latency_html = (
                f'<span class="case-latency">{r.latency_ms / 1000:.1f}s</span>' if r.latency_ms else ""
            )
            question_html = f'<div class="case-question">{_esc(r.question)}</div>' if r.question else ""
            chips = []
            for s in r.stages:
                cls = "good" if s.deterministic_passed else "critical"
                det_ok = sum(c.passed for c in s.deterministic_results)
                det_n = len(s.deterministic_results)
                chips.append(
                    f'<span class="stage-chip {cls}">{_esc(s.eval_name)} · det {det_ok}/{det_n}</span>'
                )
            chips_html = f'<div class="stage-summary">{"".join(chips)}</div>' if chips else ""

            header = f"""
            <div class="case-card" style="margin-bottom:12px;">
              <div class="case-head">
                <span class="case-id">{_esc(r.test_case_id)}</span>
                <span class="pill agent">{_esc(r.agent_name or "unknown agent")}</span>
                <span class="pill stage">e2e · {n_stages} stages</span>
                {_status_pill(r.passed)}
                {latency_html}
              </div>
              {question_html}
              {chips_html}
            </div>
            """
            st.markdown(header, unsafe_allow_html=True)

            for s in r.stages:
                stage_icon = "✅" if s.deterministic_passed else "❌"
                with st.expander(f"{stage_icon}  {s.eval_name}", expanded=False):
                    _render_stage_body(s, key_prefix=f"e2e_{r.test_case_id}")


# ---------------------------------------------------------------------------
# Sidebar + routing
# ---------------------------------------------------------------------------

def _format_run_label(run_dir: Path, latest: Path | None) -> str:
    name = run_dir.name
    # 20260720_175812 → 2026-07-20 17:58:12
    if len(name) == 15 and name[8] == "_":
        pretty = f"{name[0:4]}-{name[4:6]}-{name[6:8]} {name[9:11]}:{name[11:13]}:{name[13:15]}"
    else:
        pretty = name
    if latest is not None and run_dir.resolve() == latest.resolve():
        return f"{pretty}  (latest)"
    return pretty


with st.sidebar:
    st.header("Filters")
    results_root = st.text_input("Results root", value=DEFAULT_DASHBOARD_ROOT)
    root_path = Path(results_root)
    runs = list_runs(root_path)
    latest = resolve_latest_run(root_path)

    if runs:
        run_names = [r.name for r in runs]
        labels_by_name = {r.name: _format_run_label(r, latest) for r in runs}
        newest = run_names[0]
        # Jump to newest when a newer run appears (or on first load).
        if st.session_state.get("_known_latest_run") != newest:
            st.session_state["_known_latest_run"] = newest
            st.session_state["dashboard_run"] = newest
        elif "dashboard_run" not in st.session_state or st.session_state["dashboard_run"] not in run_names:
            st.session_state["dashboard_run"] = newest

        st.selectbox(
            "Run",
            run_names,
            format_func=lambda n: labels_by_name.get(n, n),
            key="dashboard_run",
            help="Each pytest/make eval run gets its own timestamped folder. Defaults to latest.",
        )
        output_dir = str(root_path / "runs" / st.session_state["dashboard_run"])
        st.caption(f"Loading `{st.session_state['dashboard_run']}`")
    elif latest is not None:
        # Legacy flat layout (pre-timestamp) or LATEST-only
        output_dir = str(latest)
        st.info("No timestamped runs yet — loading legacy folder. New evals write under `runs/<timestamp>/`.")
    else:
        output_dir = results_root
        st.caption("No runs found yet.")

    stage_results, e2e_results = _load_all(output_dir)

    view_options = ["By stage"]
    if e2e_results:
        view_options.append("By test case (e2e)")
    # Prefer e2e when rollups exist (demo path); stage view always available.
    default_view = 1 if e2e_results else 0
    view_mode = st.radio("View", view_options, index=default_view)

    if view_mode.startswith("By test case"):
        agents = sorted({r.agent_name for r in e2e_results if r.agent_name})
        selected_agents = st.multiselect("Agent", agents, default=agents)
        status_filter = st.radio("Status", ["All", "Passed only", "Failed only"], index=0)
        search = st.text_input("Search test case ID").strip().lower()
        selected_evals: list[str] = []
        show_eval = False
    else:
        agents = sorted({r.agent_name for r in stage_results if r.agent_name})
        eval_names = sorted({r.eval_name for r in stage_results})
        selected_agents = st.multiselect("Agent", agents, default=agents)
        selected_evals = (
            st.multiselect("Eval suite", eval_names, default=eval_names) if len(eval_names) > 1 else eval_names
        )
        status_filter = st.radio("Status", ["All", "Passed only", "Failed only"], index=0)
        search = st.text_input("Search test case ID").strip().lower()
        show_eval = len(eval_names) > 1

st.title("Agent Evaluation Dashboard")
run_label = Path(output_dir).name
if view_mode.startswith("By test case"):
    st.caption(f"E2E view · run `{run_label}` — one card per test case, stages nested.")
else:
    st.caption(f"Stage view · run `{run_label}` — one card per stage × case.")

if view_mode.startswith("By test case"):
    if not e2e_results:
        st.markdown(
            f"""
            <div class="empty-state">
              <p>No e2e rollups under <code>{_esc(output_dir)}</code>.</p>
              <p>Run <code>make demo-e2e</code> (writes <code>e2e__&lt;id&gt;.json</code>),
              or switch View to <strong>By stage</strong>.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    filtered_e2e = [
        r
        for r in e2e_results
        if (not selected_agents or r.agent_name in selected_agents)
        and (search in r.test_case_id.lower() if search else True)
        and (status_filter == "All" or (status_filter == "Passed only") == r.passed)
    ]
    if not filtered_e2e:
        st.info("No test cases match the current filters.")
        st.stop()
    _render_e2e_view(filtered_e2e)

else:
    if not stage_results:
        st.markdown(
            f"""
            <div class="empty-state">
              <p>No results found under <code>{_esc(output_dir)}</code>.</p>
              <p>Run your agent pytest suite first (e.g.
              <code>pytest tests/knowledge_agent/test_stage1.py -v -s</code>) —
              it writes one JSON file per stage × case there.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    filtered = [
        r
        for r in stage_results
        if (not selected_agents or r.agent_name in selected_agents)
        and (not selected_evals or r.eval_name in selected_evals)
        and (search in r.test_case_id.lower() if search else True)
        and (status_filter == "All" or (status_filter == "Passed only") == r.passed)
    ]
    if not filtered:
        st.info("No test cases match the current filters.")
        st.stop()
    _render_stage_view(filtered, show_eval=show_eval)
