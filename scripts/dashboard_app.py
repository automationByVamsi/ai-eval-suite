"""
Streamlit dashboard for stage-evaluation results: one card per test case,
split into a "Deterministic Checks" (Layer 1) card and a "Non-Deterministic
Checks" (Layer 2 LLM-judge) card, each with the underlying detail inside.

Reads whatever *.json StageEvaluationResult files scripts/run_stage.py or
scripts/run_stage1.py wrote under --output (default outputs/dashboard). No
agent or stage is hardcoded here - point this at a folder with results from
five different agents and it renders all five, filterable in the sidebar.

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

from src.models.evaluation_result import StageEvaluationResult

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

.empty-card { font-size:12px; color:var(--ink-muted); padding:8px 0; }
.empty-state { text-align:center; padding:70px 20px; color:var(--ink-muted); }
.empty-state code { background:var(--surface-2); padding:2px 6px; border-radius:6px; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _load_results(output_dir: str) -> list[StageEvaluationResult]:
    root = Path(output_dir)
    if not root.exists():
        return []
    results = []
    for path in sorted(root.rglob("*.json")):
        try:
            results.append(StageEvaluationResult.model_validate(json.loads(path.read_text())))
        except Exception:
            continue
    return results


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


with st.sidebar:
    st.header("Filters")
    output_dir = st.text_input("Results folder", value="outputs/dashboard")
    all_results = _load_results(output_dir)

    agents = sorted({r.agent_name for r in all_results if r.agent_name})
    stages = sorted({r.stage_name for r in all_results})
    selected_agents = st.multiselect("Agent", agents, default=agents)
    # Stages are a knowledge_agent-specific validation concept, not every
    # agent has more than one - only bother with the filter when it's
    # actually meaningful (more than one distinct stage present).
    selected_stages = st.multiselect("Stage", stages, default=stages) if len(stages) > 1 else stages
    status_filter = st.radio("Status", ["All", "Passed only", "Failed only"], index=0)
    search = st.text_input("Search test case ID").strip().lower()

st.title("Agent Evaluation Dashboard")
st.caption("Layer 1 deterministic checks + Layer 2 LLM-judge checks, per test case.")

if not all_results:
    st.markdown(
        f"""
        <div class="empty-state">
          <p>No results found under <code>{_esc(output_dir)}</code>.</p>
          <p>Run <code>python -m scripts.run_stage1</code> (or <code>run_stage.py</code>) first -
          it writes one JSON file per test case there.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

filtered = [
    r
    for r in all_results
    if (not selected_agents or r.agent_name in selected_agents)
    and (not selected_stages or r.stage_name in selected_stages)
    and (search in r.test_case_id.lower() if search else True)
    and (status_filter == "All" or (status_filter == "Passed only") == r.passed)
]

if not filtered:
    st.info("No test cases match the current filters.")
    st.stop()

total = len(filtered)
passed = sum(r.passed for r in filtered)
det_total = sum(len(r.deterministic_results) for r in filtered)
det_passed = sum(sum(c.passed for c in r.deterministic_results) for r in filtered)
judge_total = sum(len(r.metric_results) for r in filtered)
judge_passed = sum(sum(m.passed for m in r.metric_results) for r in filtered)
latencies = [r.latency_ms for r in filtered if r.latency_ms]
avg_latency_s = (sum(latencies) / len(latencies) / 1000) if latencies else None

tiles = [
    ("Test cases", str(total), ""),
    ("Overall pass rate", _pct(passed, total), "good" if passed == total else "critical"),
    ("Deterministic checks", _pct(det_passed, det_total), "good" if det_passed == det_total else "critical"),
    ("Judge checks", _pct(judge_passed, judge_total), "good" if judge_total and judge_passed == judge_total else ("" if not judge_total else "critical")),
    ("Avg latency", f"{avg_latency_s:.1f}s" if avg_latency_s is not None else "–", ""),
]
tiles_html = ['<div class="stat-row">']
for label, value, cls in tiles:
    tiles_html.append(
        f'<div class="stat-tile"><div class="label">{_esc(label)}</div>'
        f'<div class="value {cls}">{_esc(value)}</div></div>'
    )
tiles_html.append("</div>")
st.markdown("".join(tiles_html), unsafe_allow_html=True)

show_stage = len(stages) > 1

for r in sorted(filtered, key=lambda r: (r.test_case_id, r.stage_name)):
    det_rows = "".join(_det_row_html(c) for c in r.deterministic_results)
    judge_rows = "".join(_judge_row_html(m) for m in r.metric_results)
    det_passed_n = sum(c.passed for c in r.deterministic_results)
    judge_passed_n = sum(m.passed for m in r.metric_results)
    latency_html = f'<span class="case-latency">{r.latency_ms / 1000:.1f}s</span>' if r.latency_ms else ""
    question_html = f'<div class="case-question">{_esc(r.question)}</div>' if r.question else ""

    status_icon = "✅" if r.passed else "❌"
    label_bits = [f"**{r.test_case_id}**", r.agent_name or "unknown agent"]
    if show_stage:
        label_bits.append(r.stage_name)
    if r.latency_ms:
        label_bits.append(f"{r.latency_ms / 1000:.1f}s")
    label = f"{status_icon}  " + "  ·  ".join(label_bits)

    with st.expander(label, expanded=False):
        card_html = f"""
        <div class="case-card">
          <div class="case-head">
            <span class="case-id">{_esc(r.test_case_id)}</span>
            <span class="pill agent">{_esc(r.agent_name or "unknown agent")}</span>
            <span class="pill stage">{_esc(r.stage_name)}</span>
            {_status_pill(r.passed)}
            {latency_html}
          </div>
          {question_html}
          <div class="case-body-grid">
            {_check_card_html("Deterministic Checks", det_passed_n, len(r.deterministic_results), "No deterministic checks for this stage", det_rows)}
            {_check_card_html("Non-Deterministic Checks", judge_passed_n, len(r.metric_results), "No judge metrics ran for this stage", judge_rows)}
          </div>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)

        with st.expander("Agent answer"):
            st.markdown(r.answer or "_(empty)_")

        with st.expander("Retrieved context"):
            if r.context:
                for i, ctx in enumerate(r.context, start=1):
                    st.text_area(f"Context {i}", ctx, height=120, disabled=True, label_visibility="collapsed")
            else:
                st.caption("No retrieved context recorded for this stage.")

        with st.expander("Agent trace"):
            st.json(r.model_dump())
