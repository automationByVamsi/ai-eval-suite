"""
The pieces of the verdict view that aren't Streamlit calls: small HTML snippets (headline cards, the
"how the cases moved" bar, the targets table, one build's side of a comparison) and the chart that
compares the baseline with the new build. Kept apart from dashboard_verdict.py, like dashboard_parts.py.

Used by: dashboard_verdict.py only.
"""

import altair as alt
import pandas as pd

from src.core.results import ERROR, FAIL, PASS, CaseResult
from src.reporting import dashboard_parts as ui
from src.reporting import verdict_view as vv

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
    """One headline-number card. `sub_html` is already HTML (it holds the baseline and the delta)."""
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
    """One entry of the chart legend: a coloured dot (or a ring for the baseline) and its text."""
    dot = '<span class="dot ring"></span>' if ring else f'<span class="dot" style="background:{colour}"></span>'
    return f'<span class="legend-item">{dot}{text}</span>'


DUMBBELL_LEGEND = ('<div class="legend" style="margin:2px 0 6px">' + _legend_item("", "baseline", ring=True)
                   + _legend_item("var(--good)", "this build: better") + _legend_item("var(--bad)", "this build: worse")
                   + _legend_item("#64748b", "no change") + "</div>")


def rate_moved(row: dict, value: str) -> bool:
    """True when a judge / check changed between the builds (or ran in only one of them)."""
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
