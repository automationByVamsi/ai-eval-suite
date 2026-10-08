"""
How the dashboard looks: the colours (a light and a dark set), the CSS, and `html()` — the one helper
every dashboard view uses to draw a block of HTML.

Used by: the dashboard files only (dashboard.py and the dashboard_*.py views).
"""

import streamlit as st

# The colours. Everything in the CSS below refers to them by name, e.g. var(--good).
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
.grid-wrap { overflow-x:auto; }
table.grid { width:100%%; border-collapse:collapse; font-size:13px; }
table.grid th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
  font-weight:700; padding:6px 8px; border-bottom:1px solid var(--border); white-space:nowrap; }
table.grid td { padding:7px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
table.grid tr.differs td { background:var(--warn-wash); }
table.grid td.page-cell { min-width:260px; }
.absent { font-size:11.5px; color:var(--muted); font-style:italic; }
.stat-line { display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 10px; }
/* verdict view */
.vhero { position:relative; overflow:hidden; border-radius:20px; padding:26px 30px; margin-bottom:18px;
  display:flex; align-items:center; gap:28px; flex-wrap:wrap; border:1px solid var(--border);
  background:var(--hero); }
.vhero::before { content:""; position:absolute; left:0; top:0; bottom:0; width:6px; }
.vhero.good::before { background:var(--good); } .vhero.bad::before { background:var(--bad); }
.vhero-main { flex:1; min-width:280px; }
.eyebrow { font-size:11px; font-weight:750; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
.vhero-title { font-size:30px; font-weight:500; color:var(--ink); letter-spacing:-.015em; margin-top:4px; }
.vhero-title b { font-weight:800; }
.vhero-title .vs { font-size:15px; color:var(--muted); font-weight:600; margin:0 12px; letter-spacing:0; }
.vhero-reason { font-size:15px; color:var(--ink-2); margin:8px 0 10px; font-weight:550; }
.vbadge { text-align:center; padding:16px 26px; border-radius:16px; min-width:170px; }
.vbadge.good { background:var(--good-wash); } .vbadge.bad { background:var(--bad-wash); }
.vbadge-word { font-size:40px; font-weight:850; letter-spacing:.04em; line-height:1; }
.vbadge.good .vbadge-word { color:var(--good); } .vbadge.bad .vbadge-word { color:var(--bad); }
.vbadge-note { font-size:12px; font-weight:650; color:var(--ink-2); margin-top:6px; text-transform:uppercase;
  letter-spacing:.06em; }
.delta { font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }
.delta.up { color:var(--good); } .delta.down { color:var(--bad); } .delta.flat { color:var(--muted); font-weight:600; }
.stackbar { display:flex; gap:2px; height:16px; border-radius:6px; overflow:hidden; margin:10px 0 10px; }
.stackbar .seg { min-width:6px; }
.legend { display:flex; flex-wrap:wrap; gap:16px; font-size:12.5px; color:var(--ink-2); align-items:center; }
.legend-item { display:inline-flex; align-items:center; gap:6px; }
.legend-item b { color:var(--ink); font-variant-numeric:tabular-nums; }
.legend .dot { width:10px; height:10px; border-radius:3px; display:inline-block; }
.legend .dot.ring { border-radius:50%%; background:#cbd5e1; border:1.5px solid #64748b; }
.legend-total { margin-left:auto; color:var(--muted); }
table.vt td.num { font-variant-numeric:tabular-nums; white-space:nowrap; }
table.vt td { vertical-align:middle; }
.vchange { padding:10px 2px; border-top:1px solid var(--border); }
.vchange:first-child { border-top:none; }
.vchange-head { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.vrow { display:flex; gap:9px; align-items:flex-start; padding:5px 0; }
.vrow .score { margin-left:auto; }
.vsub { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:700;
  margin:10px 0 2px; }
</style>
"""


def apply_theme() -> None:
    """Put the CSS on the page, in the colours of the viewer's theme (light or dark)."""
    dark = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
    st.markdown(CSS % (DARK if dark else LIGHT), unsafe_allow_html=True)


def html(markup: str, target=st) -> None:
    """Draw a piece of HTML (on the page, or in `target`, e.g. a column)."""
    target.markdown(markup, unsafe_allow_html=True)
