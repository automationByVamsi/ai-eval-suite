"""
The release view of the dashboard. A run saved by `make verdict` opens this instead of the ordinary
run page: the new build against the baseline build.

    banner      PASS / FAIL, which two builds, and the one-line reason
    headline numbers
    tabs        Summary     how the test cases moved, release targets, judge / check charts, what changed
                Comparison  every test case with both builds' answers side by side (filters at the top)
                This build  the new build's test cases
                Baseline    the baseline build's test cases

The numbers come from verdict_view.py (no Streamlit there). The HTML snippets and the chart are in
dashboard_verdict_parts.py.

Used by: dashboard.py.
"""

import pandas as pd
import streamlit as st

from src.core.results import PASS, CaseResult, Run
from src.reporting import dashboard_parts as ui
from src.reporting import release
from src.reporting import verdict_view as vv
from src.reporting.dashboard_cases import PAGE_SIZE, render_case_list
from src.reporting.dashboard_style import html
from src.reporting.dashboard_verdict_parts import (
    CHANGE_STYLE,
    DUMBBELL_LEGEND,
    ITEM_KIND,
    NO_JUDGES,
    change_bar_html,
    compact_build_html,
    delta_html,
    dumbbell,
    rate_moved,
    targets_compare_html,
    vkpi,
)


def render_verdict(v: "vv.Verdict", status_filter: list | None, search: str) -> None:
    """Draw the whole release view for one verdict. status_filter and search come from the sidebar."""
    current, base = v.run, v.baseline_run

    # The numbers the page is built from.
    changes = vv.case_changes(v.outcome.get("rows") or [])         # per test case: regressed / improved / ...
    now_stats = ui.run_stats(current)
    was_stats = ui.run_stats(base) if base else None               # None for old baselines kept as numbers only
    _, target_rows = release.gate(current)
    base_targets = release.gate(base)[1] if base else []
    missed = sum(r["met"] is False for r in target_rows)
    reason = vv.headline(v.outcome, changes, now_stats["errors"], missed)
    questions = {c.case_id: c.question for c in [*current.cases, *(base.cases if base else [])]}

    show_banner(v, reason)
    show_kpis(changes, now_stats, was_stats)

    tab_summary, tab_compare, tab_now, tab_base = st.tabs([
        ":material/insights: Summary", f":material/compare_arrows: Comparison ({len(changes)})",
        f":material/new_releases: This build · {current.build or '?'} ({len(current.cases)})",
        f":material/history: Baseline build · {v.baseline_build} ({len(base.cases) if base else 0})"])
    with tab_summary:
        show_summary_tab(v, changes, target_rows, base_targets, questions)
    with tab_compare:
        show_comparison_tab(v, changes, questions)
    with tab_now:
        render_case_list(current, "verdict_now", status_filter, search)
    with tab_base:
        if base:
            render_case_list(base, "verdict_base", status_filter, search)
        else:
            st.info("The full baseline run isn't available for this verdict (the baseline was saved before full runs "
                    "were kept). Save a new baseline with `make baseline` to see it here.")


# --- the banner and the headline numbers ---------------------------------------------------------------

def show_banner(v: "vv.Verdict", reason: str) -> None:
    """The top banner: which build against which baseline, the reason in one line, and a big PASS / FAIL."""
    current, outcome = v.run, v.outcome
    good = v.passed
    when = pd.to_datetime(outcome.get("decided_at") or current.started_at)
    # Small grey tags under the title; a tag with empty text is left out.
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


def show_kpis(changes: dict, now_stats: dict, was_stats: dict | None) -> None:
    """Five headline numbers. Each shows the baseline's value and how it changed (was_stats is None: no baseline)."""
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


# --- Summary tab ---------------------------------------------------------------------------------------

def show_summary_tab(v: "vv.Verdict", changes: dict, target_rows: list, base_targets: list, questions: dict) -> None:
    """Top to bottom: how the cases moved, release targets, judge and check charts, what changed, notes."""
    with st.container(border=True):
        html('<div class="card-label">How the test cases moved<span class="count">per test case, all '
             'judges and checks together</span></div>')
        html(change_bar_html(changes))
    if target_rows:
        show_targets_card(target_rows, base_targets)
    show_metric_charts(v.baseline_run, v.run)
    show_what_changed(changes, v.outcome, questions)
    show_notes(v.outcome)


def show_targets_card(target_rows: list, base_targets: list) -> None:
    """The release targets of the suite: each target, the baseline's value, this build's value, met / missed."""
    missed = sum(r["met"] is False for r in target_rows)
    with st.container(border=True):
        status = ui.chip("all targets met", "good") if missed == 0 else ui.chip(f"{missed} target(s) missed", "bad")
        html(f'<div class="card-label">Release targets<span class="count">{status}</span></div>')
        html(targets_compare_html(target_rows, base_targets))


def show_metric_charts(base: Run | None, current: Run) -> None:
    """Two cards side by side: the LLM judges' mean scores, and the checks' pass rates (baseline -> this build)."""
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
        moved = [m for m in checks if rate_moved(m, "rate")]       # only the checks that changed get a line
        chart = dumbbell(moved, "rate", "pass rate", ".0%")
        if chart is not None:
            html(DUMBBELL_LEGEND)
            st.altair_chart(chart, width="stretch")
        still = [m for m in checks if not rate_moved(m, "rate")]   # the rest are listed in one sentence
        if still:
            rates = sorted({ui.pct(m["current_rate"]) for m in still})
            html(f'<div class="note" style="margin-top:6px">{len(still)} other check'
                 f'{"s" * (len(still) != 1)} unchanged (at {", ".join(rates)}): '
                 f'{ui.esc(", ".join(ui.label(m["name"]).lower() for m in still))}.</div>')
        if not checks:
            html('<div class="note">No deterministic checks ran.</div>')


def show_what_changed(changes: dict, outcome: dict, questions: dict) -> None:
    """One row per test case that moved beyond the tolerance, worst first."""
    changed = [c for c in changes.values() if c.change != "unchanged"]
    changed.sort(key=lambda c: vv.CHANGES.index(c.change))
    st.markdown('<div class="section-title">What changed</div><div class="section-note">Every test case whose '
                'results moved beyond the tolerance (pass rate ±{:.0f} pts, mean score ±{:.2f}). Open the '
                'Comparison tab to see both answers side by side.</div>'.format(
                    (outcome.get("tolerances") or {}).get("pass_rate_drop", 0.15) * 100,
                    (outcome.get("tolerances") or {}).get("score_drop", 0.10)), unsafe_allow_html=True)
    if not changed:
        st.success("No test case moved beyond the tolerance: this build behaves like the baseline.",
                   icon=":material/verified:")
        return
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


def show_notes(outcome: dict) -> None:
    """Warnings the comparison attached (e.g. judge temperature changed) and a hint for old baselines."""
    notes = sorted({r["note"] for r in outcome.get("rows") or [] if r.get("note")})
    for note in notes:
        st.warning(note, icon=":material/warning:")
    if not outcome.get("has_baseline_run"):
        st.info("This baseline was saved before full baseline runs were kept, so only its numbers are shown. "
                "Save a new baseline (`make baseline`) to compare test cases side by side.")


# --- Comparison tab ------------------------------------------------------------------------------------

def show_comparison_tab(v: "vv.Verdict", changes: dict, questions: dict) -> None:
    """Filters, a table of every test case, then one expander per case with both builds side by side."""
    picked_keys, wanted_results, text = _comparison_filters(changes)
    by_id_now, by_id_base = _by_case(v.run), _by_case(v.baseline_run)

    shown = sorted((c for c in changes.values() if _keep(c, picked_keys, wanted_results, text, questions)),
                   key=lambda c: (vv.CHANGES.index(c.change), c.case_id))
    st.caption(f"{len(shown)} of {len(changes)} test cases · worst first")
    if not shown:
        st.info("No test case matches the filters.")
        return

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
        _show_changed_case(c, questions, by_id_base.get(c.case_id, []), by_id_now.get(c.case_id, []), v,
                           expanded=len(shown) == 1)


def _comparison_filters(changes: dict) -> tuple[set, list, str]:
    """The three filters above the table. Returns (change kinds to keep, judges / checks wanted, search text)."""
    names = sorted({n for c in changes.values() for n in c.results})
    f1, f2, f3 = st.columns([2.2, 1.6, 1.4])
    picked = f1.pills("Change", [CHANGE_STYLE[k][0] for k in vv.CHANGES], selection_mode="multi",
                      default=[CHANGE_STYLE[k][0] for k in vv.CHANGES], key="v_change")
    wanted_results = f2.multiselect("Judge or check that changed", names, key="v_results",
                                    format_func=lambda n: ("judge · " if n.startswith("judge:") else "check · ")
                                    + ui.label(n.partition(":")[2]), placeholder="any judge or check")
    text = f3.text_input("Search", placeholder="case id or question", key="v_search").strip().casefold()
    picked_keys = {k for k in vv.CHANGES if CHANGE_STYLE[k][0] in (picked or [])}
    return picked_keys, wanted_results, text


def _keep(c, picked_keys: set, wanted_results: list, text: str, questions: dict) -> bool:
    """True when a test case passes all three filters."""
    if c.change not in picked_keys:
        return False
    if wanted_results and not any(i["name"] in wanted_results for i in c.items if i["status"] != "ok"):
        return False
    question = questions.get(c.case_id, "")
    return not text or text in c.case_id.casefold() or text in question.casefold()


def _show_changed_case(c, questions: dict, base_reps: list, now_reps: list, v: "vv.Verdict", expanded: bool) -> None:
    """One expander: what changed, the question, then the baseline build and the new build side by side."""
    label_, _, _, colour, icon = CHANGE_STYLE[c.change]
    moved = " · ".join(vv.describe(i) for i in c.items if i["status"] != "ok")
    title = (f":{colour}[**{label_.upper()}**]  ·  **{c.case_id}**  ·  "
             f"{ui.short(questions.get(c.case_id, ''), 70)}" + (f"  —  {moved}" if moved else ""))
    with st.expander(title, icon=icon, expanded=expanded):
        if c.items:
            html('<div class="chips">' + "".join(
                ui.chip(vv.describe(i), ITEM_KIND.get(i["status"], "ghost"), title=i.get("note", ""))
                for i in c.items) + "</div>")
        html(f'<div class="question" style="margin:8px 0 12px">'
             f'{ui.esc(questions.get(c.case_id, ""))}</div>')
        left, right = st.columns(2, gap="medium")
        render_side(base_reps[0] if base_reps else None, base_reps, left, f"Baseline · build {v.baseline_build}")
        render_side(now_reps[0] if now_reps else None, now_reps, right, f"This build · {v.run.build or '?'}")


def render_side(case: CaseResult | None, reps: list, col, title: str) -> None:
    """One build's side of a comparison: its status and scores, the answer, and the pages used."""
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


def _by_case(r: Run | None) -> dict[str, list[CaseResult]]:
    """{case id: its repetitions in order}. Empty when there is no run."""
    out: dict[str, list[CaseResult]] = {}
    for c in (r.cases if r else []):
        out.setdefault(c.case_id, []).append(c)
    return {k: sorted(v, key=lambda c: c.rep) for k, v in out.items()}


def _status_text(reps: list | None) -> str:
    """'PASS' for one run of a case, '3/5 passed' for several, '–' when the case isn't in this build."""
    if not reps:
        return "–"
    if len(reps) == 1:
        return reps[0].status.upper()
    return f"{sum(c.status == PASS for c in reps)}/{len(reps)} passed"
