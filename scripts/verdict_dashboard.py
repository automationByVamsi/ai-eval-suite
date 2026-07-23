"""
Streamlit dashboard for VERDICT reliability reports.

Reads JSON under outputs/verdict/runs/ (VerdictReport aggregates + baseline diffs).

    streamlit run scripts/verdict_dashboard.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.verdict.models import VerdictReport

DEFAULT_ROOT = Path("outputs/verdict")
RUNS_DIR = DEFAULT_ROOT / "runs"

st.set_page_config(page_title="VERDICT Dashboard", page_icon="⚖️", layout="wide")

CSS = """
<style>
:root {
  --surface: #fcfcfb; --surface-2: #ffffff; --page: #f9f9f7;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --border: rgba(11,11,11,0.10); --track: #e1e0d9;
  --good: #0ca30c; --critical: #d03b3b; --warn: #c47f00;
  --good-wash: rgba(12,163,12,0.10); --critical-wash: rgba(208,59,59,0.10);
  --warn-wash: rgba(196,127,0,0.12);
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1f1f1e; --surface-2: #262625; --page: #0d0d0d;
    --ink: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --border: rgba(255,255,255,0.14); --track: #383835;
    --good: #0ca30c; --critical: #e66767; --warn: #e0a84a;
    --good-wash: rgba(12,163,12,0.16); --critical-wash: rgba(230,103,103,0.18);
    --warn-wash: rgba(224,168,74,0.16);
  }
}
html, body, [class*="css"] { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }

.stat-row { display:flex; gap:14px; flex-wrap:wrap; margin: 4px 0 22px 0; }
.stat-tile { flex:1; min-width:140px; background:var(--surface); border:1px solid var(--border);
  border-radius:14px; padding:16px 18px; }
.stat-tile .label { font-size:12px; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; }
.stat-tile .value { font-size:26px; font-weight:700; color:var(--ink); font-variant-numeric: tabular-nums; margin-top:2px; }
.stat-tile .value.good { color: var(--good); }
.stat-tile .value.critical { color: var(--critical); }
.stat-tile .value.warn { color: var(--warn); }

.pill { display:inline-flex; align-items:center; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.pill.good { background:var(--good-wash); color:var(--good); }
.pill.critical { background:var(--critical-wash); color:var(--critical); }
.pill.warn { background:var(--warn-wash); color:var(--warn); }
.pill.muted { background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border); }

.meter-track { position:relative; height:8px; border-radius:4px; background:var(--track); margin-top:4px; }
.meter-fill { position:absolute; top:0; left:0; height:100%; border-radius:4px; }
.meter-fill.good { background:var(--good); }
.meter-fill.critical { background:var(--critical); }
.meter-fill.warn { background:var(--warn); }

.empty-state { text-align:center; padding:70px 20px; color:var(--ink-muted); }
.empty-state code { background:var(--surface-2); padding:2px 6px; border-radius:6px; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _list_reports(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _load_report(path: Path) -> VerdictReport | None:
    try:
        return VerdictReport.model_validate(json.loads(path.read_text()))
    except Exception:
        return None


def _pct(rate: float) -> str:
    return f"{rate * 100:.0f}%"


def _rate_cls(rate: float) -> str:
    if rate >= 1.0:
        return "good"
    if rate <= 0.0:
        return "critical"
    return "warn"


def _stat_tiles(tiles: list[tuple[str, str, str]]) -> None:
    parts = ['<div class="stat-row">']
    for label, value, cls in tiles:
        parts.append(
            f'<div class="stat-tile"><div class="label">{_esc(label)}</div>'
            f'<div class="value {cls}">{_esc(value)}</div></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _pass_rate_bar(rate: float) -> str:
    cls = _rate_cls(rate)
    width = max(0.0, min(1.0, rate)) * 100
    return (
        f'<div class="meter-track">'
        f'<div class="meter-fill {cls}" style="width:{width:.0f}%"></div></div>'
    )


st.title("VERDICT")
st.caption("Reliability distributions + baseline regressions (wraps existing stage contracts)")

with st.sidebar:
    st.header("Run")
    root = Path(st.text_input("VERDICT root", str(DEFAULT_ROOT)))
    runs_dir = root / "runs"
    reports = _list_reports(runs_dir)
    if not reports:
        st.warning("No reports found")
        selected = None
    else:
        labels = {p.name: p for p in reports}
        choice = st.selectbox("Report", list(labels.keys()), index=0)
        selected = labels[choice]
        st.caption(f"`{selected}`")
    only_issues = st.checkbox("Only flaky / regressions", value=False)
    st.markdown("---")
    st.markdown(
        "Generate reports:\n\n"
        "```bash\nmake verdict-demo\n```\n\n"
        "Then refresh this page."
    )

if selected is None:
    st.markdown(
        '<div class="empty-state">'
        "<p>No VERDICT reports yet.</p>"
        "<p>Run <code>make verdict-demo</code> (uses <code>python3</code>), "
        "then open this dashboard.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

report = _load_report(selected)
if report is None:
    st.error(f"Could not parse {selected}")
    st.stop()

gate_ok = not report.has_regression
gate_label = "OK" if gate_ok else "FAIL"
gate_cls = "good" if gate_ok else "critical"
flaky_n = sum(1 for a in report.aggregates if 0.0 < a.pass_rate < 1.0)
reg_n = sum(1 for d in report.diffs if d.status == "regression")
improved_n = sum(1 for d in report.diffs if d.status == "improved")

_stat_tiles(
    [
        ("Gate", gate_label, gate_cls),
        ("Reps (N)", str(report.n_reps), ""),
        ("Checks", str(len(report.aggregates)), ""),
        ("Flaky", str(flaky_n), "warn" if flaky_n else "good"),
        ("Regressions", str(reg_n), "critical" if reg_n else "good"),
    ]
)

meta = (
    f'<span class="pill muted">{_esc(report.profile)}</span> '
    f'<span class="pill muted">tag={_esc(report.tag)}</span> '
    f'<span class="pill muted">judges={"on" if report.run_judges else "off"}</span> '
)
if report.simulate_regression:
    meta += ' <span class="pill warn">simulate-regression</span>'
if report.single_run_all_passed and flaky_n:
    meta += ' <span class="pill warn">single-run would look PASS*</span>'
elif report.single_run_all_passed:
    meta += ' <span class="pill good">single-run all PASS</span>'
st.markdown(meta, unsafe_allow_html=True)

# --- Distributions ---
st.subheader("Distributions")
agg_rows = []
for a in report.aggregates:
    if only_issues and not (0.0 < a.pass_rate < 1.0):
        continue
    score = ""
    if a.mean_score is not None:
        std = a.std_score or 0.0
        score = f"{a.mean_score:.2f} ± {std:.2f}"
    label = a.single_run_label
    agg_rows.append(
        {
            "case": a.test_case_id,
            "stage": a.stage,
            "check": a.name,
            "kind": a.kind,
            "pass_rate": a.pass_rate,
            "pass %": _pct(a.pass_rate),
            "single-run": label,
            "score": score or "—",
            "n": a.n,
        }
    )

if not agg_rows:
    st.info("No rows match the current filter.")
else:
    for row in agg_rows:
        c1, c2, c3 = st.columns([3, 1, 2])
        with c1:
            st.markdown(
                f"**{row['case']}** · `{row['stage']}` · `{row['check']}`  \n"
                f"<span class='pill muted'>{_esc(row['kind'])}</span> "
                f"<span class='pill {_rate_cls(row['pass_rate'])}'>{_esc(row['single-run'])}</span>",
                unsafe_allow_html=True,
            )
        with c2:
            st.metric("Pass rate", row["pass %"])
        with c3:
            st.markdown(_pass_rate_bar(row["pass_rate"]), unsafe_allow_html=True)
            if row["score"] != "—":
                st.caption(f"score {row['score']} (n={row['n']})")
            else:
                st.caption(f"n={row['n']}")

    with st.expander("Table view"):
        st.dataframe(
            [
                {
                    "case": r["case"],
                    "stage": r["stage"],
                    "check": r["check"],
                    "kind": r["kind"],
                    "pass_rate": r["pass %"],
                    "single_run": r["single-run"],
                    "score": r["score"],
                    "n": r["n"],
                }
                for r in agg_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

# --- Baseline diffs ---
st.subheader("vs baseline")
if not report.diffs:
    st.info("No baseline diff in this report. Save a baseline first, then re-run without `--no-compare`.")
else:
    diff_rows = [
        d
        for d in report.diffs
        if (not only_issues) or d.status in {"regression", "improved", "new"}
    ]
    if only_issues:
        diff_rows = [d for d in diff_rows if d.status != "ok"]

    if not diff_rows:
        st.success("No regressions / improvements under the current filter.")
    else:
        # Summary chips
        st.markdown(
            f'<span class="pill critical">{reg_n} regression</span> '
            f'<span class="pill good">{improved_n} improved</span>',
            unsafe_allow_html=True,
        )
        table = []
        for d in diff_rows:
            table.append(
                {
                    "case": d.test_case_id,
                    "stage": d.stage,
                    "check": d.name,
                    "kind": d.kind,
                    "baseline": _pct(d.baseline_pass_rate),
                    "current": _pct(d.current_pass_rate),
                    "delta_pp": round(d.delta * 100, 1),
                    "status": d.status,
                }
            )
        st.dataframe(table, use_container_width=True, hide_index=True)

        regressions = [d for d in diff_rows if d.status == "regression"]
        if regressions:
            st.markdown("#### Regressions")
            for d in regressions:
                st.markdown(
                    f"- **{d.test_case_id}** `{d.stage}` / `{d.name}`: "
                    f"{_pct(d.baseline_pass_rate)} → {_pct(d.current_pass_rate)} "
                    f"({d.delta * 100:+.1f}pp)"
                )

st.markdown("---")
st.caption(
    f"Gate: **{gate_label}** · single-run all passed: {report.single_run_all_passed} · "
    f"source `{selected.name}`"
)
