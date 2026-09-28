"""
Streamlit dashboard for A/B comparative evaluation results.

Reads outputs/comparison/<experiment>/comparison_result.json (ComparisonResult)
and renders the Step-8 gate, per-metric verdicts with CI-vs-margin bars, the
paired per-case table, safety events, the similarity screen (with A vs B answer
text for divergent cases when the fixture / traces are resolvable), judge
reliability and operations.

    make comparison-dashboard
    streamlit run scripts/comparison_dashboard.py
"""

from __future__ import annotations

import html
import json
import sys
from collections import defaultdict
from pathlib import Path

# `streamlit run` puts only scripts/ on sys.path — add the repo root so `src`
# is importable regardless of how this is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.comparison.models import (
    ComparisonResult,
    MetricComparison,
    MetricRole,
    MetricVerdict,
)

DEFAULT_ROOT = Path("outputs/comparison")
CONFIGS_DIR = Path("configs/comparisons")

st.set_page_config(page_title="A/B Comparison Dashboard", page_icon="⚖️", layout="wide")

CSS = """
<style>
:root {
  --surface: #fcfcfb; --surface-2: #ffffff; --page: #f9f9f7;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --border: rgba(11,11,11,0.10); --track: #e1e0d9;
  --good: #0ca30c; --critical: #d03b3b; --warn: #c47f00; --info: #2f6fdb;
  --good-wash: rgba(12,163,12,0.10); --critical-wash: rgba(208,59,59,0.10);
  --warn-wash: rgba(196,127,0,0.12); --info-wash: rgba(47,111,219,0.12);
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1f1f1e; --surface-2: #262625; --page: #0d0d0d;
    --ink: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --border: rgba(255,255,255,0.14); --track: #383835;
    --good: #0ca30c; --critical: #e66767; --warn: #e0a84a; --info: #7aa2f7;
    --good-wash: rgba(12,163,12,0.16); --critical-wash: rgba(230,103,103,0.18);
    --warn-wash: rgba(224,168,74,0.16); --info-wash: rgba(122,162,247,0.16);
  }
}
html, body, [class*="css"] { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }

.stat-row { display:flex; gap:14px; flex-wrap:wrap; margin: 4px 0 22px 0; }
.stat-tile { flex:1; min-width:150px; background:var(--surface); border:1px solid var(--border);
  border-radius:14px; padding:16px 18px; }
.stat-tile .label { font-size:12px; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; }
.stat-tile .value { font-size:26px; font-weight:700; color:var(--ink); font-variant-numeric: tabular-nums; margin-top:2px; }
.stat-tile .value.good { color: var(--good); }
.stat-tile .value.critical { color: var(--critical); }
.stat-tile .value.warn { color: var(--warn); }
.stat-tile .sub { font-size:12px; color:var(--ink-muted); margin-top:2px; }

.pill { display:inline-flex; align-items:center; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }
.pill.good { background:var(--good-wash); color:var(--good); }
.pill.critical { background:var(--critical-wash); color:var(--critical); }
.pill.warn { background:var(--warn-wash); color:var(--warn); }
.pill.info { background:var(--info-wash); color:var(--info); }
.pill.muted { background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border); }

.check-row { display:flex; align-items:flex-start; gap:10px; padding:8px 0; border-top:1px solid var(--border); }
.check-row:first-of-type { border-top:none; }
.check-icon { font-size:14px; width:18px; text-align:center; flex-shrink:0; font-weight:700; }
.check-icon.good { color:var(--good); }
.check-icon.critical { color:var(--critical); }
.check-name { font-size:14px; color:var(--ink); }

.metric-card { border:1px solid var(--border); border-radius:16px; background:var(--surface);
  padding:18px 20px; margin-bottom:16px; }
.metric-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.metric-name { font-size:17px; font-weight:700; color:var(--ink); margin-right:4px; }
.metric-note { font-size:12px; color:var(--ink-2); margin-top:6px; }

.ci-wrap { margin: 10px 0 4px 0; }
.ci-labels { display:flex; justify-content:space-between; font-size:11px; color:var(--ink-muted);
  font-variant-numeric: tabular-nums; }
.ci-track { position:relative; height:14px; border-radius:7px; background:var(--track); margin:4px 0; }
.ci-fill { position:absolute; top:3px; height:8px; border-radius:4px; }
.ci-fill.good { background:var(--good); }
.ci-fill.critical { background:var(--critical); }
.ci-fill.warn { background:var(--warn); }
.ci-zero { position:absolute; top:-3px; width:2px; height:20px; background:var(--ink); border-radius:1px; }
.ci-margin { position:absolute; top:-3px; width:0; height:20px; border-left:2px dashed var(--critical); }
.ci-point { position:absolute; top:4px; width:6px; height:6px; margin-left:-3px; border-radius:50%; background:var(--surface-2); border:1px solid var(--ink); }
.ci-legend { font-size:11px; color:var(--ink-muted); margin-top:2px; }

.answer-box { border:1px solid var(--border); border-radius:10px; background:var(--surface-2);
  padding:10px 12px; font-size:13px; color:var(--ink); white-space:pre-wrap; margin-bottom:8px; }
.answer-label { font-size:11px; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:4px; }

.empty-state { text-align:center; padding:70px 20px; color:var(--ink-muted); }
.empty-state code { background:var(--surface-2); padding:2px 6px; border-radius:6px; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- helpers


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _fmt(value: float | None, digits: int = 3, signed: bool = False) -> str:
    if value is None:
        return "—"
    spec = f"{{:{'+' if signed else ''}.{digits}f}}"
    return spec.format(value)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


VERDICT_CLS = {
    MetricVerdict.IMPROVEMENT: "good",
    MetricVerdict.EQUIVALENT: "good",
    MetricVerdict.ACCEPTABLE_REGRESSION: "warn",
    MetricVerdict.INCONCLUSIVE: "muted",
    MetricVerdict.FAIL: "critical",
}

ROLE_CLS = {
    MetricRole.PRIMARY: "info",
    MetricRole.GUARDRAIL: "info",
    MetricRole.SAFETY: "critical",
    MetricRole.DIAGNOSTIC: "muted",
}


def _list_results(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths = list(root.glob("*/comparison_result.json"))
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _load_result(path: Path) -> ComparisonResult | None:
    try:
        return ComparisonResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):  # ValueError covers JSONDecodeError + pydantic ValidationError
        return None


def _stat_tiles(tiles: list[tuple[str, str, str, str]]) -> None:
    parts = ['<div class="stat-row">']
    for label, value, cls, sub in tiles:
        sub_html = f'<div class="sub">{_esc(sub)}</div>' if sub else ""
        parts.append(
            f'<div class="stat-tile"><div class="label">{_esc(label)}</div>'
            f'<div class="value {cls}">{_esc(value)}</div>{sub_html}</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _pill(text: str, cls: str) -> str:
    return f'<span class="pill {cls}">{_esc(text)}</span>'


def _ci_bar(m: MetricComparison) -> str:
    """Horizontal CI bar with markers at 0 and at −δ (non-inferiority margin)."""
    b = m.bootstrap
    if b is None or b.n_pairs == 0:
        return '<div class="ci-legend">No bootstrap available.</div>'
    margin = m.non_inferiority.margin if m.non_inferiority else None
    neg_margin = -abs(margin) if margin is not None else None

    points = [b.ci_low, b.ci_high, 0.0, b.observed_mean_delta]
    if neg_margin is not None:
        points.extend([neg_margin, abs(margin)])
    lo, hi = min(points), max(points)
    span = hi - lo
    if span <= 0:
        span = abs(hi) or 1.0
    pad = span * 0.12
    lo -= pad
    hi += pad
    span = hi - lo

    def x(v: float) -> float:
        return max(0.0, min(100.0, (v - lo) / span * 100.0))

    if neg_margin is not None:
        cls = "good" if b.ci_low > neg_margin else "critical"
        if cls == "good" and b.ci_high < 0:
            cls = "warn"  # inside margin but entirely negative
    else:
        cls = "good" if b.ci_low > 0 else ("critical" if b.ci_high < 0 else "warn")

    left = x(b.ci_low)
    width = max(0.6, x(b.ci_high) - left)
    parts = ['<div class="ci-wrap">']
    parts.append(
        f'<div class="ci-labels"><span>{_fmt(lo, 3, True)}</span>'
        f'<span>Δ (oriented: + = B better)</span><span>{_fmt(hi, 3, True)}</span></div>'
    )
    parts.append('<div class="ci-track">')
    parts.append(f'<div class="ci-fill {cls}" style="left:{left:.2f}%; width:{width:.2f}%"></div>')
    parts.append(f'<div class="ci-zero" style="left:{x(0.0):.2f}%"></div>')
    if neg_margin is not None:
        parts.append(f'<div class="ci-margin" style="left:{x(neg_margin):.2f}%"></div>')
    parts.append(f'<div class="ci-point" style="left:{x(b.observed_mean_delta):.2f}%"></div>')
    parts.append("</div>")
    legend = (
        f"CI95 [{_fmt(b.ci_low, 4, True)}, {_fmt(b.ci_high, 4, True)}] · "
        f"observed {_fmt(b.observed_mean_delta, 4, True)} · "
        f"one-sided lower {_fmt(b.one_sided_lower, 4, True)} · "
        f"inflation {b.inflation:g} · {b.n_bootstrap} resamples · n={b.n_pairs}"
    )
    if neg_margin is not None:
        legend += f" · dashed = −δ ({_fmt(neg_margin, 4, True)})"
    parts.append(f'<div class="ci-legend">{_esc(legend)}</div></div>')
    return "".join(parts)


def _resolve_answers(result: ComparisonResult, result_path: Path) -> dict[str, dict[str, list[str]]]:
    """
    Best-effort: case_id -> {"a": [answers...], "b": [answers...]}.

    Offline: find the experiment YAML by name, load its fixtures.path.
    Live:    read agentOutput from outputs/comparison/<name>/traces/{a,b}/rep_N/**/<case>.json.
    """
    answers: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"a": [], "b": []})

    # Live traces (always try — cheap directory scan)
    traces_root = result_path.parent / "traces"
    if traces_root.is_dir():
        for arm in ("a", "b"):
            for p in sorted((traces_root / arm).rglob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    cid = str((data.get("test_case") or {}).get("test_case_id") or p.stem)
                    out = (data.get("raw_output") or {}).get("agentOutput")
                    if out:
                        answers[cid][arm].append(str(out))
                except (OSError, ValueError, AttributeError):
                    continue  # unreadable / non-trace JSON — skip silently in a viewer
        if answers:
            return answers

    # Offline fixture via experiment YAML
    if not CONFIGS_DIR.is_dir():
        return answers
    try:
        from src.core.config import load_yaml
    except ImportError:
        return answers
    fixture_path: Path | None = None
    for yaml_path in sorted(CONFIGS_DIR.glob("*.yaml")):
        try:
            raw = load_yaml(yaml_path).get("comparison") or {}
        except (OSError, ValueError, TypeError):
            continue  # malformed experiment YAML — not this dashboard's job to report
        if str(raw.get("name") or "") != result.experiment_name:
            continue
        fixtures = raw.get("fixtures") or {}
        fp = fixtures.get("path") if isinstance(fixtures, dict) else raw.get("fixtures_path")
        if fp:
            fixture_path = Path(str(fp))
        break
    if fixture_path is None or not fixture_path.is_file():
        return answers
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        rows = data.get("observations") if isinstance(data, dict) else data
        seen: set[tuple[str, str, int]] = set()
        for row in rows or []:
            arm = row.get("candidate")
            cid = str(row.get("test_case_id"))
            rep = int(row.get("rep") or 0)
            ans = row.get("answer")
            if arm in ("a", "b") and ans and (cid, arm, rep) not in seen:
                seen.add((cid, arm, rep))
                answers[cid][arm].append(str(ans))
    except (OSError, ValueError, TypeError, AttributeError):
        return answers  # fixture unreadable — fall back to IDs only
    return answers


# --------------------------------------------------------------------------- sidebar

st.title("A/B Comparison")
st.caption("Paired Candidate A vs Candidate B · inflated bootstrap p_NI · Step-8 gate (no weighted score)")

with st.sidebar:
    st.header("Experiment")
    root = Path(st.text_input("Comparison root", str(DEFAULT_ROOT)))
    results = _list_results(root)
    if not results:
        st.warning("No comparison results found")
        selected = None
    else:
        labels = {p.parent.name: p for p in results}
        choice = st.selectbox("Result", list(labels.keys()), index=0)
        selected = labels[choice]
        st.caption(f"`{selected}`")
    show_paired = st.checkbox("Show per-case paired tables", value=True)
    show_answers = st.checkbox("Load A/B answers for divergent cases", value=True)
    st.markdown("---")
    st.markdown(
        "Generate results:\n\n"
        "```bash\nmake comparison-demo\nmake comparison-demo-safety\n```\n\n"
        "Then refresh this page."
    )

if selected is None:
    st.markdown(
        '<div class="empty-state">'
        "<p>No comparison results yet.</p>"
        "<p>Run <code>make comparison-demo</code>, then open this dashboard.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

result = _load_result(selected)
if result is None:
    st.error(f"Could not parse {selected}")
    st.stop()

gate = result.gate

# --------------------------------------------------------------------------- header

meta = (
    _pill(f"dimension={result.dimension.value}", "muted")
    + " "
    + _pill(f"mode={result.mode}", "muted")
    + " "
    + _pill(f"reps={result.repetitions}", "muted")
    + " "
    + _pill(f"dataset={result.dataset_agent}/{result.dataset_suite}", "muted")
    + " "
    + _pill(f"eval={result.evaluation_suite}", "muted")
)
st.markdown(f"### {_esc(result.experiment_name)}", unsafe_allow_html=True)
if result.description:
    st.caption(result.description)
st.markdown(meta, unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    st.markdown(
        f"**Candidate A** · {_pill(result.candidate_a.name, 'info')} "
        f"`{_esc(result.candidate_a.agent)}`",
        unsafe_allow_html=True,
    )
    if result.candidate_a.metadata:
        st.caption(json.dumps(result.candidate_a.metadata))
with col_b:
    st.markdown(
        f"**Candidate B** · {_pill(result.candidate_b.name, 'info')} "
        f"`{_esc(result.candidate_b.agent)}`",
        unsafe_allow_html=True,
    )
    if result.candidate_b.metadata:
        st.caption(json.dumps(result.candidate_b.metadata))

for w in result.warnings:
    st.warning(w)

# --------------------------------------------------------------------------- tiles

primary = [m for m in result.per_metric if m.role == MetricRole.PRIMARY]
primary_verdict = primary[0].verdict.value if primary else "—"
primary_cls = VERDICT_CLS.get(primary[0].verdict, "") if primary else ""
if primary_cls == "muted":
    primary_cls = ""
n_conditions = len(gate.conditions) if gate else 0
n_passed = sum(1 for v in gate.conditions.values() if v) if gate else 0
b_safety_events = sum(s.candidate_b_events for s in result.safety)
safety_cls = "critical" if any(not s.passed for s in result.safety) else "good"

ship = bool(gate and gate.ship)
_stat_tiles(
    [
        ("Gate", "SHIP" if ship else "DO NOT SHIP", "good" if ship else "critical",
         "shadow → canary" if ship else "blocked"),
        ("Primary", primary_verdict, primary_cls,
         primary[0].metric_name if primary else "no primary metric"),
        ("Conditions", f"{n_passed}/{n_conditions}", "good" if n_passed == n_conditions else "critical",
         "Step-8 checks passed"),
        ("Metrics", str(len(result.per_metric)), "",
         (f"{len(primary)} primary · "
          f"{sum(1 for m in result.per_metric if m.role == MetricRole.GUARDRAIL)} guardrail")),
        ("Safety events (B)", str(b_safety_events), safety_cls if result.safety else "",
         f"{len(result.safety)} critical metric(s)" if result.safety else "none configured"),
    ]
)

# --------------------------------------------------------------------------- gate

st.subheader("Step-8 gate")
if gate is None:
    st.info("No gate result in this file.")
else:
    g1, g2 = st.columns([3, 2])
    with g1:
        rows = []
        for key in sorted(gate.conditions):
            ok = gate.conditions[key]
            icon = "✓" if ok else "✗"
            cls = "good" if ok else "critical"
            rows.append(
                f'<div class="check-row"><div class="check-icon {cls}">{icon}</div>'
                f'<div class="check-name">{_esc(key)}</div></div>'
            )
        st.markdown("".join(rows), unsafe_allow_html=True)
    with g2:
        st.markdown("**Reasons**")
        for r in gate.reasons:
            if ship:
                st.success(r)
            else:
                st.error(r)

# --------------------------------------------------------------------------- metrics

st.subheader("Per-metric verdicts")
st.caption(
    "p_NI = share of inflated bootstrap resamples with Δ ≤ −δ (pass when < α). "
    "p_diff = Wilcoxon / McNemar 'any change?' test. Verdict = p_NI × p_diff × sign(Δ)."
)

summary_rows = []
for m in result.per_metric:
    b = m.bootstrap
    summary_rows.append(
        {
            "metric": m.metric_name,
            "role": m.role.value,
            "A": _fmt(m.candidate_a_mean),
            "B": _fmt(m.candidate_b_mean),
            "Δ": _fmt(m.observed_delta, 3, True),
            "CI95": f"[{_fmt(b.ci_low, 4, True)}, {_fmt(b.ci_high, 4, True)}]" if b else "—",
            "δ": _fmt(m.non_inferiority.margin) if m.non_inferiority else "—",
            "p_NI": _fmt(b.p_ni, 4) if b and b.p_ni is not None else "—",
            "p_diff": _fmt(m.wilcoxon.p_value, 4) if m.wilcoxon and m.wilcoxon.p_value is not None else "—",
            "verdict": m.verdict.value,
        }
    )
st.dataframe(summary_rows, width="stretch", hide_index=True)

for m in result.per_metric:
    verdict_cls = VERDICT_CLS.get(m.verdict, "muted")
    head = (
        f'<div class="metric-head"><span class="metric-name">{_esc(m.metric_name)}</span>'
        + _pill(m.role.value, ROLE_CLS.get(m.role, "muted"))
        + _pill(m.direction.value, "muted")
        + _pill(m.verdict.value, verdict_cls)
        + (_pill("demoted: unreliable judge", "warn") if m.demoted_unreliable_judge else "")
        + "</div>"
    )
    st.markdown(f'<div class="metric-card">{head}', unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("A mean", _fmt(m.candidate_a_mean))
    c2.metric("B mean", _fmt(m.candidate_b_mean), delta=_fmt(m.observed_delta, 3, True))
    c3.metric("p_NI", _fmt(m.bootstrap.p_ni, 4) if m.bootstrap and m.bootstrap.p_ni is not None else "—")
    c4.metric(
        "p_diff",
        _fmt(m.wilcoxon.p_value, 4) if m.wilcoxon and m.wilcoxon.p_value is not None else "—",
    )
    wtl = m.win_tie_loss
    c5.metric("B win / tie / A win", f"{wtl.b_better} / {wtl.tie} / {wtl.a_better}" if wtl else "—")

    st.markdown(_ci_bar(m), unsafe_allow_html=True)

    extras = []
    if m.non_inferiority:
        extras.append(
            f"non-inferiority δ={m.non_inferiority.margin:g}: "
            f"{'satisfied' if m.non_inferiority.satisfied else 'NOT satisfied'}"
        )
    if m.degraded_case_share is not None:
        extras.append(f"degraded cases {_pct(m.degraded_case_share)}")
    if m.improved_case_share is not None:
        extras.append(f"improved cases {_pct(m.improved_case_share)}")
    if m.mcnemar:
        extras.append(
            f"McNemar b01={m.mcnemar.b01} b10={m.mcnemar.b10} p={_fmt(m.mcnemar.p_value, 4)}"
        )
    if m.wilcoxon and m.wilcoxon.note:
        extras.append(m.wilcoxon.note)
    st.markdown(
        f'<div class="metric-note">{_esc(m.note)}<br/>{_esc(" · ".join(extras))}</div>',
        unsafe_allow_html=True,
    )

    if show_paired and m.paired:
        with st.expander(f"Per-case pairs · {m.metric_name} ({len(m.paired)} cases)"):
            paired_rows = [
                {
                    "case": p.test_case_id,
                    "A runs": len(p.candidate_a_runs),
                    "B runs": len(p.candidate_b_runs),
                    "A mean": _fmt(p.candidate_a_mean),
                    "B mean": _fmt(p.candidate_b_mean),
                    "Δ (oriented)": _fmt(p.oriented_delta, 3, True),
                    "missing": p.missing,
                }
                for p in sorted(
                    m.paired,
                    key=lambda p: (p.oriented_delta if p.oriented_delta is not None else 0.0),
                )
            ]
            st.dataframe(paired_rows, width="stretch", hide_index=True)
    if m.top_regressions or m.top_improvements:
        with st.expander(f"Top regressions / improvements · {m.metric_name}"):
            r1, r2 = st.columns(2)
            with r1:
                st.markdown("**Top regressions**")
                if m.top_regressions:
                    for c in m.top_regressions:
                        st.markdown(
                            f"- **{c.test_case_id}** A={_fmt(c.candidate_a_mean)} "
                            f"B={_fmt(c.candidate_b_mean)} Δ={_fmt(c.oriented_delta, 3, True)}"
                        )
                else:
                    st.caption("none")
            with r2:
                st.markdown("**Top improvements**")
                if m.top_improvements:
                    for c in m.top_improvements:
                        st.markdown(
                            f"- **{c.test_case_id}** A={_fmt(c.candidate_a_mean)} "
                            f"B={_fmt(c.candidate_b_mean)} Δ={_fmt(c.oriented_delta, 3, True)}"
                        )
                else:
                    st.caption("none")
    st.markdown("</div>", unsafe_allow_html=True)

# --------------------------------------------------------------------------- safety

st.subheader("Safety (hard gate)")
if not result.safety:
    st.info("No critical / safety metrics configured for this experiment.")
else:
    for s in result.safety:
        cls = "good" if s.passed else "critical"
        st.markdown(
            f"{_pill('PASS' if s.passed else 'FAIL', cls)} **{_esc(s.metric_name)}** · "
            f"A events={s.candidate_a_events} · B events={s.candidate_b_events} · "
            f"allowed={s.allowed_events} · n_trials_B={s.n_trials_b}"
            + (
                f" · rule-of-three upper bound={_fmt(s.rule_of_three_upper_bound, 4)}"
                if s.rule_of_three_upper_bound is not None
                else ""
            ),
            unsafe_allow_html=True,
        )
        if s.note:
            st.caption(s.note)

# --------------------------------------------------------------------------- similarity

st.subheader("Similarity screen (triage)")
sim = result.similarity
if sim is None:
    st.info("No similarity screen — observations lacked answer / embedding data.")
else:
    band_cls = "good" if sim.inside_band else ("warn" if sim.divergences_reviewed else "critical")
    _stat_tiles(
        [
            ("S_AA", f"{_fmt(sim.s_aa_mean)} ± {_fmt(sim.s_aa_std)}", "", "A vs A across reps"),
            ("S_BB", f"{_fmt(sim.s_bb_mean)} ± {_fmt(sim.s_bb_std)}", "", "B vs B across reps"),
            ("S_AB", f"{_fmt(sim.s_ab_mean)} ± {_fmt(sim.s_ab_std)}", "", "A vs B same case"),
            ("T_sim", _fmt(sim.t_sim), "", "5th pct of S_AA"),
            (
                "Divergent",
                f"{len(sim.divergent_case_ids)}/{sim.n_cases}",
                band_cls,
                "SME reviewed" if sim.divergences_reviewed else ("inside band" if sim.inside_band else "review required"),
            ),
        ]
    )
    chips = (
        _pill(f"method={sim.method}", "muted")
        + " "
        + _pill("consistency ok" if sim.consistency_ok else "B less consistent", "good" if sim.consistency_ok else "critical")
        + " "
        + (_pill("divergences reviewed", "good") if sim.divergences_reviewed else _pill("not reviewed", "warn"))
    )
    st.markdown(chips, unsafe_allow_html=True)
    if sim.note:
        st.caption(sim.note)
    if sim.consistency_note:
        st.caption(sim.consistency_note)

    if sim.divergent_case_ids:
        answers = _resolve_answers(result, selected) if show_answers else {}
        with st.expander(f"Divergent cases ({len(sim.divergent_case_ids)}) — A vs B answers", expanded=False):
            if not answers:
                st.caption(
                    "Answer text not resolvable (no fixture match under configs/comparisons or traces under "
                    f"{selected.parent / 'traces'}). Showing IDs only."
                )
                st.write(", ".join(sim.divergent_case_ids))
            else:
                pick = st.selectbox("Case", sim.divergent_case_ids, key="divergent_case")
                a_ans = answers.get(pick, {}).get("a", [])
                b_ans = answers.get(pick, {}).get("b", [])
                ca, cb = st.columns(2)
                with ca:
                    st.markdown(f'<div class="answer-label">Candidate A · {len(a_ans)} run(s)</div>', unsafe_allow_html=True)
                    for i, txt in enumerate(a_ans):
                        st.markdown(f'<div class="answer-box"><b>rep {i}</b><br/>{_esc(txt)}</div>', unsafe_allow_html=True)
                    if not a_ans:
                        st.caption("no A answers found")
                with cb:
                    st.markdown(f'<div class="answer-label">Candidate B · {len(b_ans)} run(s)</div>', unsafe_allow_html=True)
                    for i, txt in enumerate(b_ans):
                        st.markdown(f'<div class="answer-box"><b>rep {i}</b><br/>{_esc(txt)}</div>', unsafe_allow_html=True)
                    if not b_ans:
                        st.caption("no B answers found")
                st.caption(
                    "Sign-off is recorded via `divergences_reviewed: true` in the experiment YAML "
                    "(gate condition 4)."
                )

# --------------------------------------------------------------------------- stability

st.subheader("Stability (A/A · B/B null tests)")
if not result.stability:
    st.info("Stability not run (require_stability: false or --no-stability).")
else:
    st.dataframe(
        [
            {
                "arm": s.arm.upper(),
                "metric": s.metric_name,
                "Δ": _fmt(s.observed_mean_delta, 4, True),
                "CI95": f"[{_fmt(s.ci_low, 4, True)}, {_fmt(s.ci_high, 4, True)}]",
                "n_pairs": s.n_pairs,
                "resolution": _fmt(s.resolution, 4),
                "δ": _fmt(s.margin),
                "enforceable": "—" if s.tolerance_enforceable is None else s.tolerance_enforceable,
                "stable": s.appears_stable,
                "note": s.note,
            }
            for s in result.stability
        ],
        width="stretch",
        hide_index=True,
    )

# --------------------------------------------------------------------------- judge + ops

j1, j2 = st.columns(2)
with j1:
    st.subheader("Judge reliability")
    if not result.judge_variance:
        st.info("No judge variance estimates.")
    else:
        st.dataframe(
            [
                {
                    "metric": jv.metric_name,
                    "role": jv.role.value,
                    "σ_judge": _fmt(jv.sigma_judge, 4),
                    "σ_gen": _fmt(jv.sigma_gen, 4),
                    "reliable": jv.reliable,
                    "demoted": jv.demoted,
                    "note": jv.note,
                }
                for jv in result.judge_variance
            ],
            width="stretch",
            hide_index=True,
        )
with j2:
    st.subheader("Operations")
    ops = result.operations
    st.dataframe(
        [
            {
                "": "Latency median (ms)",
                "A": _fmt(ops.candidate_a_latency_median_ms, 1),
                "B": _fmt(ops.candidate_b_latency_median_ms, 1),
            },
            {
                "": "Latency p95 (ms)",
                "A": _fmt(ops.candidate_a_latency_p95_ms, 1),
                "B": _fmt(ops.candidate_b_latency_p95_ms, 1),
            },
            {
                "": "Cost / task",
                "A": _fmt(ops.candidate_a_cost_mean, 4),
                "B": _fmt(ops.candidate_b_cost_mean, 4),
            },
        ],
        width="stretch",
        hide_index=True,
    )
    budget_bits = []
    if ops.latency_within_budget is not None:
        budget_bits.append(
            _pill("latency within budget" if ops.latency_within_budget else "latency over budget",
                  "good" if ops.latency_within_budget else "critical")
        )
    if ops.cost_within_budget is not None:
        budget_bits.append(
            _pill("cost within budget" if ops.cost_within_budget else "cost over budget",
                  "good" if ops.cost_within_budget else "critical")
        )
    if budget_bits:
        st.markdown(" ".join(budget_bits), unsafe_allow_html=True)
    st.caption(ops.cost_note)

st.markdown("---")
st.caption(
    f"Gate: **{'SHIP' if ship else 'DO NOT SHIP'}** · source `{selected}`"
)
