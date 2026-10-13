"""
Export one run as a single, self-contained HTML file (`make report`, or "Download HTML report" in the
dashboard): the dashboard's Overview, Test cases and Consistency views, with the same look, readable in
any browser without Streamlit, Python or a network — to attach to an email, a ticket or a PR.

    make report AGENT=knowledge_agent SUITE=golden [RUN=<run id>]   ->  outputs/reports/<run id>.html

It reuses the dashboard's HTML pieces (dashboard_parts) and CSS (dashboard_style), so the two stay alike.
Interactive parts work offline: tabs, status filter and search over test cases, expandable cases, and
per-case tabs (fields, stage timings, test case, raw result). Trends (other runs) are dashboard-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.core import paths
from src.core.results import ERROR, FAIL, PASS, SKIP, CaseResult, Run
from src.reporting import dashboard_parts as ui
from src.reporting import release
from src.reporting.dashboard_style import CSS, DARK, LIGHT
from src.reporting.summary import summarise, time_split

STATUS_KIND = {PASS: "good", FAIL: "bad", ERROR: "warn", SKIP: "muted"}


def write_report(run: Run, out: Path | None = None) -> Path:
    """Write the run's HTML report and return its path (default outputs/reports/<run id>.html)."""
    out = Path(out) if out else paths.OUTPUTS_DIR / "reports" / f"{run.run_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_html(run), encoding="utf-8")
    return out


def report_html(run: Run) -> str:
    """The whole report as one HTML document (inline CSS and JS, no external files)."""
    stats = ui.run_stats(run)
    consistency_rows = release.consistency(run) if run.reps > 1 else []
    tabs = [("overview", "Overview", _overview(run, stats, consistency_rows)),
            ("cases", f"Test cases ({len(run.cases)})", _cases(run))]
    if consistency_rows:
        tabs.append(("consistency", "Consistency", _consistency(run, consistency_rows)))
    baseline = _baseline(run)
    if baseline:
        tabs.append(("baseline", "Baseline", baseline))
    buttons = "".join(f'<button class="tab{" on" * (i == 0)}" data-tab="{key}">{ui.esc(name)}</button>'
                      for i, (key, name, _) in enumerate(tabs))
    panels = "".join(f'<section class="panel{" on" * (i == 0)}" id="{key}">{body}</section>'
                     for i, (key, _, body) in enumerate(tabs))
    title = f"{run.agent.replace('_', ' ').title()} · {run.suite} · {run.run_id}"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{ui.esc(title)}</title>'
            f'{_css()}</head><body><main>{_header(run, stats)}<nav class="tabs">{buttons}</nav>{panels}'
            f'<footer>Exported from ai-eval-suite · {ui.esc(run.run_id)} · a snapshot of this run '
            f'(Trends across runs are in the live dashboard: make dashboard)</footer></main>{_JS}</body></html>')


# --- page parts ----------------------------------------------------------------------------------

def _header(run: Run, stats: dict) -> str:
    """The hero box: agent, run chips and the one-line result (as the dashboard's header)."""
    mode = "offline replay" if run.offline else "live agent"
    when = pd.to_datetime(run.started_at).strftime("%d %b %Y, %H:%M") if run.started_at else ""
    sub = "".join(ui.chip(x, k) for x, k in [
        (run.suite, "accent"), (f"build {run.build}" if run.build else "no build label", "plain"),
        (mode, "plain"), (f"{run.reps} rep{'s' * (run.reps > 1)}", "plain"), (when, "ghost"),
        (run.run_id, "ghost")] if x)
    if stats["errors"]:
        word, kind = f"{stats['errors']} case{'s' * (stats['errors'] > 1)} could not be evaluated", "warn"
    elif stats["failed"]:
        word, kind = f"{stats['failed']} of {stats['cases']} cases failed", "bad"
    else:
        word, kind = "All cases passed", "good"
    judges = ", ".join(run.metrics) if run.metrics else "none"
    checks = "all" if run.checks is None else ("none" if not run.checks else ", ".join(run.checks))
    return (f'<div class="hero"><div><div class="hero-title">{ui.esc(run.agent.replace("_", " ").title())}</div>'
            f'<div class="hero-sub">{sub}</div></div><div class="verdict"><span class="verdict-word {kind}">'
            f'{ui.esc(word)}</span><div class="verdict-note">LLM judges: {ui.esc(judges)} · checks: '
            f'{ui.esc(checks)}</div></div></div>')


def _overview(run: Run, stats: dict, consistency_rows: list[dict]) -> str:
    """KPIs, stage times, release targets, consistency, scoreboards, cases needing attention, heatmap."""
    case_rate = stats["passed"] / stats["cases"] if stats["cases"] else None
    judged = stats["judges"][PASS] + stats["judges"][FAIL]
    checked = stats["checks"][PASS] + stats["checks"][FAIL]
    mean = f" · mean score {stats['mean_score']:.2f}" if stats["mean_score"] is not None else ""
    latency = f"{stats['median_s']:.1f}s" if stats["median_s"] is not None else "–"
    parts = ['<div class="kpis">' + "".join([
        ui.kpi("Cases passing", ui.pct(case_rate), f"{stats['passed']} of {stats['cases']} test cases",
               ui.tone(case_rate)),
        ui.kpi("LLM judges", ui.pct(stats["judge_rate"]),
               f"{stats['judges'][PASS]}/{judged} verdicts passed{mean}", ui.tone(stats["judge_rate"])),
        ui.kpi("Deterministic checks", ui.pct(stats["check_rate"]),
               f"{stats['checks'][PASS]}/{checked} passed · {stats['checks'][SKIP]} skipped",
               ui.tone(stats["check_rate"])),
        ui.kpi("Could not evaluate", str(stats["errors"]), "cases with an error (not counted as fails)",
               "warn" if stats["errors"] else "good"),
        ui.kpi("Latency", latency, f"median · p95 {stats['p95_s']:.1f}s" if stats["p95_s"] else "median", "accent"),
    ]) + "</div>"]

    split = time_split([run])
    if split:
        total = sum(split.values())
        parts.append('<div class="kpis">' + "".join(
            ui.kpi(f"{name.capitalize()} time", f"{seconds:.1f}s",
                   f"mean per case · {seconds / total:.0%} of these stages" if total else "mean per case")
            for name, seconds in split.items()) + "</div>")

    gate_ok, target_rows = release.gate(run)
    if target_rows:
        missed = sum(r["met"] is False for r in target_rows)
        status = ui.chip("all targets met", "good") if gate_ok else ui.chip(f"{missed} target(s) missed", "bad")
        parts.append(_card(f'<div class="card-label">Release targets<span class="count">{status}</span></div>'
                           + ui.targets_html(target_rows)))

    if consistency_rows:
        ok, total = sum(r["consistent"] for r in consistency_rows), len(consistency_rows)
        badge = ui.chip(f"{ok} of {total} cases consistent", "good" if ok == total else "bad")
        bad = "".join(f'<div class="check"><span class="icon bad">✗</span><div><span class="row-name">'
                      f'{ui.esc(r["case"])}</span><div class="row-reason">{ui.esc(r["why"])}</div></div></div>'
                      for r in consistency_rows if not r["consistent"])
        parts.append(_card(f'<div class="card-label">Consistency over {run.reps} runs<span class="count">{badge}'
                           f'</span></div>' + (bad or '<div class="note">Every case gave the same result in every '
                                                      'run.</div>')))

    summary = summarise([run])
    parts.append('<div class="cols2">'
                 + _card('<div class="card-label">LLM judges<span class="count">pass rate across cases</span></div>'
                         + ui.scoreboard_html(summary, "judge"))
                 + _card('<div class="card-label">Deterministic checks<span class="count">pass rate across cases'
                         '</span></div>' + ui.check_scoreboard_html(summary))
                 + "</div>")
    parts.append(_needs_attention(run))
    parts.append(_heatmap(run))
    return "".join(parts)


def _needs_attention(run: Run) -> str:
    """A table of every case that did not pass, with its first reason."""
    head = ('<div class="section-title">Needs attention</div><div class="section-note">Every case that failed or '
            'could not be evaluated, with the first reason. Open it in the Test cases tab for the full picture.</div>')
    attention = [c for c in run.cases if c.status != PASS]
    if not attention:
        return head + '<div class="ok-box">Nothing to look at: every case passed.</div>'
    rows = "".join(
        f'<tr><td>{ui.chip(c.status.upper(), STATUS_KIND[c.status] + "-soft")}</td>'
        f'<td class="mono">{ui.esc(_case_name(c, run.reps))}</td><td>{ui.esc(c.question or "")}</td>'
        f'<td>{ui.esc(ui.first_issue(c))}</td><td>{ui.ran(ui.tally(ui.split(c)[0]))}</td>'
        f'<td>{ui.ran(ui.tally([r for g in ui.split(c)[1].values() for r in g]))}</td></tr>'
        for c in attention)
    return (head + '<div class="grid-wrap"><table class="grid"><tr><th>Status</th><th>Case</th><th>Question</th>'
            f'<th>Why</th><th>Judges</th><th>Checks</th></tr>{rows}</table></div>')


def _heatmap(run: Run) -> str:
    """Every case × every result, as coloured cells; hover a cell for why (the dashboard's heatmap)."""
    names: dict[str, str] = {"Agent & setup": "setup"}
    for c in run.cases:
        for r in c.results:
            if not ui.is_setup(r):
                names.setdefault(ui.label(r.name), "judge" if r.kind == "judge" else "check")
    order = sorted(names, key=lambda n: {"setup": 0, "judge": 1, "check": 2}[names[n]])
    if len(order) == 1:
        return ""
    head = "".join(f'<th class="rot"><span>{ui.esc(n)}</span></th>' for n in order)
    rows = []
    for c in run.cases:
        cells = {ui.label(r.name): r for r in c.results if not ui.is_setup(r)}
        trouble = ui.problems(c)
        tds = [f'<td class="hm {"warn" if trouble else "good"}" title="'
               f'{ui.esc(trouble[0]["title"] if trouble else "the agent answered")}"></td>']
        for n in order[1:]:
            r = cells.get(n)
            if r is None:
                tds.append('<td class="hm none"></td>')
            else:
                why = r.reason or ("passed" if r.status == PASS else "")
                tds.append(f'<td class="hm {STATUS_KIND.get(r.status, "muted")}" '
                           f'title="{ui.esc(f"{r.status.upper()} · {why}")}"></td>')
        rows.append(f'<tr><th class="mono">{ui.esc(_case_name(c, run.reps))}</th>{"".join(tds)}</tr>')
    legend = "".join(f'<span class="legend-item"><span class="dot hm {k}"></span>{w}</span>'
                     for w, k in [("pass", "good"), ("fail", "bad"), ("error", "warn"), ("skip", "muted")])
    return ('<div class="section-title">Every case × every result</div><div class="section-note">Columns: could it '
            'be evaluated, then LLM judges, then checks. Hover a cell for why.</div>'
            f'<div class="legend" style="margin-bottom:8px">{legend}</div>'
            f'<div class="grid-wrap"><table class="heat"><tr><th></th>{head}</tr>{"".join(rows)}</table></div>')


def _cases(run: Run) -> str:
    """The filter bar and one expandable block per case, problems first (as the Test cases tab)."""
    cases = sorted(run.cases, key=lambda c: {ERROR: 0, FAIL: 1, PASS: 2}[c.status])
    bar = ('<div class="filters"><label><input type="checkbox" value="fail" checked> Fail</label>'
           '<label><input type="checkbox" value="error" checked> Error</label>'
           '<label><input type="checkbox" value="pass" checked> Pass</label>'
           '<input type="search" placeholder="case id, question or answer text">'
           f'<span class="muted shown">{len(cases)} of {len(cases)} cases</span></div>'
           '<div class="section-note">Problems first. Left: what was asked and answered. '
           'Right: LLM judges, then deterministic checks.</div>')
    return bar + "".join(_case(c, run, i) for i, c in enumerate(cases)) + \
        '<div class="note none-match" hidden>No case matches the filters.</div>'


def _case(case: CaseResult, run: Run, index: int) -> str:
    """One case: summary line, problems, answer column, results column and debug tabs."""
    judges, groups = ui.split(case)
    checks = [r for g in groups.values() for r in g]
    tail = []
    if judges:
        tail.append(f"judges {ui.ran(ui.tally(judges))}")
    if checks:
        tail.append(f"checks {ui.ran(ui.tally(checks))}")
    if case.latency_ms:
        tail.append(f"{case.latency_ms / 1000:.1f}s")
    rep = f" · rep {case.rep + 1}" if run.reps > 1 else ""
    search = " ".join(v or "" for v in (case.case_id, case.question, case.answer)).casefold()
    summary = (f'<span class="st {STATUS_KIND[case.status]}">{case.status.upper()}</span>'
               f'<b>{ui.esc(case.case_id)}</b>{rep} · {ui.esc(ui.short(case.question or case.description or "", 90))}'
               f'<span class="tail">{" · ".join(tail)}</span>')
    body = "".join(ui.problem_html(p) for p in ui.problems(case))
    body += f'<div class="cols"><div>{_answer_column(case)}</div><div>{_results_column(case, run)}</div></div>'
    body += _debug_tabs(case, index)
    return (f'<details class="case" data-status="{case.status}" data-text="{ui.esc(search)}">'
            f'<summary>{summary}</summary><div class="case-body">{body}</div></details>')


def _answer_column(case: CaseResult) -> str:
    """Question, the agent's answer, the reference answer and the evidence pages."""
    d = case.details or {}
    extra = {k: v for k, v in case.input.items() if k != "question" and v not in (None, "")}
    out = [_card('<div class="card-label">Question</div>'
                 f'<div class="question">{ui.esc(case.question or "-")}</div>'
                 + ('<div class="chips">' + "".join(ui.chip(f"{k}: {ui.short(v, 40)}") for k, v in extra.items())
                    + "</div>" if extra else "")
                 + (f'<div class="row-reason">{ui.esc(case.description)}</div>' if case.description else ""))]

    meta = []
    if d.get("question_type"):
        meta.append(ui.chip(f"type: {d['question_type']}", "accent"))
    if d.get("confidence"):
        conf = str(d["confidence"]).upper()
        meta.append(ui.chip(f"confidence: {conf}",
                            {"HIGH": "good-soft", "MEDIUM": "warn-soft", "LOW": "bad-soft"}.get(conf, "plain")))
    if case.answer:
        answer = f'<div class="md">{_markdown(case.answer)}</div>'
    elif d.get("agent_error"):
        expected = (case.expected or {}).get("expected_error")
        answer = (f'<div class="note">The agent refused with an error'
                  f'{" (this case expects one: " + ui.esc(", ".join(expected)) + ")" if expected else ""}:</div>'
                  f'<pre>{ui.esc(str(d["agent_error"])[:1500])}</pre>')
    else:
        answer = '<div class="note">No answer.</div>'
    notes = [*ui.as_list(d.get("caveats")), *ui.as_list(d.get("user_warnings"))]
    answer += "".join(f'<div class="caption">ⓘ {ui.esc(n)}</div>' for n in notes)
    out.append(_card(f'<div class="card-label">Agent answer<span class="count">{"".join(meta)}</span></div>{answer}'))

    reference = (f'<div class="md">{_markdown(case.expected_answer)}</div>' if case.expected_answer else
                 '<div class="note">This case has no reference answer, so correctness is skipped.</div>')
    out.append(_card(f'<div class="card-label">Expected answer (reference)</div>{reference}'))

    pages, missed = ui.evidence_pages(case), ui.expected_pages_missed(case)
    if pages or missed:
        body = "".join(ui.page_html(p) for p in pages)
        if missed:
            body += f'<div class="missed">✗ Expected but not in the evidence: {ui.esc(", ".join(missed))}</div>'
        if pages and not any(p["text"] for p in pages):
            body += '<div class="note">Page text was not fetched in this suite (no judge needed it).</div>'
        body += ('<div class="caption">anchor = chosen first · expanded = related pages added · cited = in the '
                 'answer · expected = a page the test case expects</div>')
        out.append(_card(f'<div class="card-label">Supporting evidence<span class="count">{len(pages)} page'
                         f'{"s" * (len(pages) != 1)}</span></div>{body}'))
    return "".join(out)


def _results_column(case: CaseResult, run: Run) -> str:
    """LLM judges, then deterministic checks by group."""
    judges, groups = ui.split(case)
    judge_body = "".join(ui.judge_html(r) for r in judges) if judges else \
        '<div class="note">This suite runs no LLM judges.</div>'
    checks = [r for g in groups.values() for r in g]
    counts = ui.tally(checks)
    skipped = f" · {counts[SKIP]} skipped" if counts[SKIP] else ""
    if checks:
        check_body = ui.checks_html(groups)
    elif run.checks == []:
        check_body = '<div class="note">This suite runs no deterministic checks (checks: none in agent.yaml).</div>'
    else:
        check_body = '<div class="note">No checks ran for this case.</div>'
    return (_card(f'<div class="card-label">LLM judges<span class="count">'
                  f'{ui.ran(ui.tally(judges)) + " passed" if judges else ""}</span></div>{judge_body}')
            + _card(f'<div class="card-label">Deterministic checks<span class="count">'
                    f'{ui.ran(counts) + " passed" + skipped if checks else ""}</span></div>{check_body}'))


def _debug_tabs(case: CaseResult, index: int) -> str:
    """Pipeline fields, stage timings, the test case and the raw result, as small tabs."""
    d = case.details or {}
    fields = ("".join(f'<tr><td class="mono">{ui.esc(k)}</td><td>{ui.esc(ui.short(v, 300))}</td></tr>'
                      for k, v in d.items() if k != "contexts") if d else "")
    fields_body = (f'<div class="grid-wrap scroll"><table class="grid"><tr><th>field</th><th>value</th></tr>{fields}'
                   '</table></div>' if fields else
                   '<div class="note">No fields saved for this case (older run, or the case errored before '
                   'reading the trace).</div>')
    if case.trace:
        fields_body += f'<div class="caption">Trace: <span class="mono">{ui.esc(case.trace)}</span></div>'

    split = {k.removesuffix("_seconds"): v for k, v in d.items()
             if k.endswith("_seconds") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    stages = d.get("stage_seconds")
    timing = (" · ".join(f"<b>{ui.esc(n)}</b> {s:.1f}s" for n, s in split.items()) if split else "")
    if isinstance(stages, dict) and stages:
        top = max((v for v in stages.values() if isinstance(v, (int, float))), default=0) or 1
        timing += "".join(f'<div class="tbar"><span class="mono">{ui.esc(k)}</span><div class="bar"><div '
                          f'class="bar-fill accentbg" style="width:{100 * v / top:.1f}%"></div></div>'
                          f'<span class="mono">{v:.2f}s</span></div>'
                          for k, v in stages.items() if isinstance(v, (int, float)))
    timing = timing or '<div class="note">No stage timings in this trace.</div>'

    test_case = json.dumps({"input": case.input, "expected": case.expected}, indent=2, ensure_ascii=False,
                           default=str)
    raw = json.dumps({"case_id": case.case_id, "rep": case.rep, "status": case.status, "error": case.error,
                      "results": [r.__dict__ for r in case.results]}, indent=2, ensure_ascii=False, default=str)
    tabs = [("Pipeline fields", fields_body), ("Stage timings", timing),
            ("Test case", f"<pre>{ui.esc(test_case)}</pre>"), ("Raw result", f"<pre>{ui.esc(raw)}</pre>")]
    group = f"c{index}"
    buttons = "".join(f'<button class="tab small{" on" * (i == 0)}" data-tab="{group}-{i}">{name}</button>'
                      for i, (name, _) in enumerate(tabs))
    panels = "".join(f'<div class="panel{" on" * (i == 0)}" id="{group}-{i}">{body}</div>'
                     for i, (_, body) in enumerate(tabs))
    return f'<div class="subtabs"><nav class="tabs">{buttons}</nav>{panels}</div>'


def _consistency(run: Run, consistency_rows: list[dict]) -> str:
    """One block per repeated case: the rule, pages used in each run and each run's answer."""
    spec = run.consistency or {}
    reps_by_case: dict[str, list[CaseResult]] = {}
    for c in run.cases:
        reps_by_case.setdefault(c.case_id, []).append(c)
    rule = []
    if spec.get("same"):
        rule.append(f"the {release.field_label(spec['same'])} are the same in every run")
    rule.append(f"{', '.join(ui.label(n).lower() for n in spec.get('all_pass') or ['every LLM judge'])} "
                "passes in every run")
    out = [f'<div class="section-note">Each case was asked {run.reps} times. A case is consistent when '
           f'{" and ".join(rule)}. The wording of the answer may differ.</div>']
    for row in consistency_rows:
        reps = sorted(reps_by_case[row["case"]], key=lambda c: c.rep)
        ok = row["consistent"]
        why = (f"same {release.field_label(row['same'])} in every run" if row["same"] else
               "same result in every run") if ok else row["why"]
        chips = []
        if row["same"]:
            chips.append(ui.chip(f"{release.field_label(row['same'])}: {row['overlap']:.0%} in common",
                                 "good-soft" if row["overlap"] >= spec.get("min_overlap", 1.0) else "bad-soft"))
        for name, value in row["passes"].items():
            k, n = (int(x) for x in value.split("/"))
            chips.append(ui.chip(f"{ui.label(name).lower()} passed {k} of {n}", "good-soft" if k == n else "bad-soft"))
        for field, overlap in row["also"].items():
            chips.append(ui.chip(f"{release.field_label(field)}: {overlap:.0%} in common", "ghost"))
        grid = ui.pages_by_run(reps)
        body = (f'<div class="question">{ui.esc(reps[0].question or "-")}</div>'
                f'<div class="stat-line">{"".join(chips)}</div>')
        if grid:
            body += ('<div class="card-label">Pages used in each run</div>' + ui.pages_grid_html(grid, len(reps))
                     + '<div class="caption">Highlighted rows changed between runs.</div>')
        body += '<div class="card-label" style="margin-top:14px">The answer in each run</div>'
        body += "".join(_card(f'<div class="stat-line">{ui.chip(f"Run {c.rep + 1}", "accent")}'
                              f'{ui.chip(c.status.upper(), STATUS_KIND[c.status] + "-soft")}</div>'
                              f'<div class="md">{_markdown(c.answer) if c.answer else "<em>No answer.</em>"}</div>')
                        for c in reps)
        out.append(f'<details class="case"{" open" * (not ok)}><summary><span class="st '
                   f'{"good" if ok else "bad"}">{"CONSISTENT" if ok else "INCONSISTENT"}</span><b>'
                   f'{ui.esc(row["case"])}</b> · {ui.esc(why)}</summary><div class="case-body">{body}</div></details>')
    return "".join(out)


def _baseline(run: Run) -> str:
    """This run against the saved baseline, if there is one (the dashboard's Baseline tab)."""
    from src.verdict.baseline import baseline_path
    from src.verdict.compare import compare
    if not baseline_path(run.agent, run.suite).is_file():
        return ""
    try:
        passed, rows, baseline = compare(run)
    except Exception:  # noqa: BLE001 — a baseline in an old format must not stop the export
        return ""
    regressions = [r for r in rows if r["status"] in ("regression", "missing")]
    word = "No regressions" if passed else f"{len(regressions)} regression{'s' * (len(regressions) != 1)}"
    order = {"regression": 0, "missing": 1, "improved": 2, "new": 3, "ok": 4}

    def num(v: Any) -> str:
        return "" if v is None else f"{v:.0%}" if isinstance(v, float) and v <= 1 else ui.esc(v)
    body = "".join(
        f'<tr><td>{ui.esc(r["status"].upper())}</td><td class="mono">{ui.esc(r["result"])}</td>'
        f'<td>{num((r["baseline"] or {}).get("pass_rate"))}</td><td>{num((r["current"] or {}).get("pass_rate"))}</td>'
        f'<td>{ui.esc((r["baseline"] or {}).get("mean_score") or "")}</td>'
        f'<td>{ui.esc((r["current"] or {}).get("mean_score") or "")}</td><td>{ui.esc(r["note"])}</td></tr>'
        for r in sorted(rows, key=lambda r: order.get(r["status"], 9)))
    return (f'<div class="hero"><div><div class="hero-title">{ui.esc(word)}</div><div class="hero-sub">build '
            f'{ui.esc(run.build or "?")} against baseline build {ui.esc(baseline.get("build") or "?")}</div></div>'
            f'<div class="verdict"><span class="verdict-word {"good" if passed else "bad"}">'
            f'{"PASS" if passed else "FAIL"}</span></div></div><div class="grid-wrap"><table class="grid"><tr>'
            '<th>Status</th><th>Case :: result</th><th>Baseline pass rate</th><th>Current pass rate</th>'
            f'<th>Baseline score</th><th>Current score</th><th>Note</th></tr>{body}</table></div>')


# --- helpers -------------------------------------------------------------------------------------

def _card(inner: str) -> str:
    return f'<div class="card">{inner}</div>'


def _case_name(case: CaseResult, reps: int) -> str:
    return case.case_id + (f" · rep {case.rep + 1}" if reps > 1 else "")


def _markdown(text: str) -> str:
    """A small Markdown-to-HTML: headings, bullet and numbered lists, bold, italics, code and links —
    enough for agent answers, without an extra package."""
    def inline(s: str) -> str:
        s = ui.esc(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", s)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)

    out, para, kind = [], [], None
    def close_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
            para.clear()
    def close_list() -> None:
        nonlocal kind
        if kind:
            out.append(f"</{kind}>")
            kind = None
    for raw in str(text).splitlines():
        line = raw.strip()
        bullet = re.match(r"^[-*•]\s+(.*)", line)
        number = re.match(r"^\d+[.)]\s+(.*)", line)
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if not line:
            close_para()
            close_list()
        elif heading:
            close_para()
            close_list()
            out.append(f"<h4>{inline(heading.group(2))}</h4>")
        elif bullet or number:
            close_para()
            want = "ul" if bullet else "ol"
            if kind != want:
                close_list()
                out.append(f"<{want}>")
                kind = want
            out.append(f"<li>{inline((bullet or number).group(1))}</li>")
        else:
            close_list()
            para.append(line)
    close_para()
    close_list()
    return "".join(out)


def _css() -> str:
    """The dashboard's CSS (light, and dark when the viewer's system is dark) plus the page shell."""
    style = CSS % LIGHT
    dark = DARK.replace("\n", " ")
    return style.replace("</style>", "@media (prefers-color-scheme: dark) { :root { " + dark + " } }\n"
                         + _SHELL + "</style>")


_SHELL = """
body { margin:0; background:var(--surface-2); color:var(--ink);
  font-family:"Source Sans 3","Source Sans Pro",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
main { max-width:1400px; margin:0 auto; padding:28px 32px 40px; }
footer { margin-top:30px; font-size:12px; color:var(--muted); text-align:center; }
a { color:var(--accent); }
.card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px 16px;
  margin-bottom:12px; }
.cols, .cols2 { display:grid; grid-template-columns:1.15fr 1fr; gap:16px; align-items:start; }
.cols2 { grid-template-columns:1fr 1fr; gap:22px; margin:6px 0 10px; }
@media (max-width:900px) { .cols, .cols2 { grid-template-columns:1fr; } }
nav.tabs { display:flex; gap:4px; border-bottom:1px solid var(--border); margin:6px 0 18px; flex-wrap:wrap; }
button.tab { border:none; background:none; padding:9px 14px; font-size:14px; font-weight:600; color:var(--ink-2);
  cursor:pointer; border-bottom:2px solid transparent; font-family:inherit; }
button.tab.on { color:var(--accent); border-bottom-color:var(--accent); }
button.tab.small { font-size:12.5px; padding:6px 10px; }
.panel { display:none; } .panel.on { display:block; }
.subtabs { margin-top:6px; } .subtabs nav.tabs { margin:4px 0 10px; }
details.case { background:var(--surface); border:1px solid var(--border); border-radius:12px; margin-bottom:10px; }
details.case > summary { cursor:pointer; padding:11px 14px; font-size:14px; color:var(--ink); list-style:none;
  display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
details.case > summary::-webkit-details-marker { display:none; }
details.case > summary::before { content:"▸"; color:var(--muted); }
details.case[open] > summary::before { content:"▾"; }
details.case > summary .tail { color:var(--muted); font-size:12.5px; margin-left:auto; }
.case-body { padding:4px 14px 14px; }
.st { font-size:11.5px; font-weight:800; padding:1px 8px; border-radius:6px; }
.st.good { background:var(--good-wash); color:var(--good); }
.st.bad { background:var(--bad-wash); color:var(--bad); }
.st.warn { background:var(--warn-wash); color:var(--warn); }
.st.muted { background:var(--surface-2); color:var(--muted); }
.filters { display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-bottom:6px; font-size:14px; }
.filters input[type=search] { flex:1; min-width:220px; padding:7px 10px; border-radius:8px; font-size:14px;
  border:1px solid var(--border); background:var(--surface); color:var(--ink); font-family:inherit; }
.md { font-size:14.5px; line-height:1.55; color:var(--ink); } .md p { margin:0 0 8px; }
.md ul, .md ol { margin:0 0 8px; padding-left:22px; } .md h4 { margin:10px 0 4px; font-size:15px; }
.md code, pre { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
pre { background:var(--surface-2); border:1px solid var(--border); border-radius:8px; padding:10px 12px;
  font-size:12px; white-space:pre-wrap; word-break:break-word; max-height:420px; overflow:auto; color:var(--ink); }
.caption { font-size:12px; color:var(--muted); margin-top:6px; }
.scroll { max-height:320px; overflow:auto; }
.ok-box { background:var(--good-wash); color:var(--good); border-radius:10px; padding:10px 14px; font-weight:600; }
table.heat { border-collapse:separate; border-spacing:2px; font-size:12px; }
table.heat th { font-weight:600; color:var(--ink-2); text-align:left; padding-right:8px; white-space:nowrap; }
table.heat th.rot { height:150px; vertical-align:bottom; padding:0; }
table.heat th.rot span { display:inline-block; writing-mode:vertical-rl; transform:rotate(180deg); padding:4px 0; }
td.hm { width:26px; height:22px; border-radius:4px; }
.hm.good { background:#16a34a; } .hm.bad { background:#dc2626; } .hm.warn { background:#d97706; }
.hm.muted { background:#94a3b8; } .hm.none { background:var(--track); opacity:.4; }
.legend .dot.hm { width:12px; height:12px; }
.tbar { display:grid; grid-template-columns:220px 1fr 70px; gap:10px; align-items:center; font-size:12px; }
.bar-fill.accentbg { background:var(--accent); }
"""

_JS = """<script>
document.addEventListener('click', function (e) {
  var b = e.target.closest('button.tab'); if (!b) return;
  var nav = b.parentElement, scope = nav.parentElement;
  nav.querySelectorAll('button.tab').forEach(function (x) { x.classList.toggle('on', x === b); });
  Array.prototype.forEach.call(scope.children, function (el) {
    if (el.classList.contains('panel')) el.classList.toggle('on', el.id === b.dataset.tab);
  });
});
(function () {
  var panel = document.getElementById('cases'); if (!panel) return;
  var boxes = panel.querySelectorAll('.filters input[type=checkbox]');
  var search = panel.querySelector('.filters input[type=search]');
  var cases = panel.querySelectorAll('details.case'), shown = panel.querySelector('.shown');
  var none = panel.querySelector('.none-match');
  function apply() {
    var want = {}; boxes.forEach(function (b) { want[b.value] = b.checked; });
    var q = search.value.trim().toLowerCase(), n = 0;
    cases.forEach(function (c) {
      var ok = want[c.dataset.status] && (!q || c.dataset.text.indexOf(q) >= 0);
      c.hidden = !ok; if (ok) n++;
    });
    shown.textContent = n + ' of ' + cases.length + ' cases'; none.hidden = n > 0;
    if (n === 1) cases.forEach(function (c) { if (!c.hidden) c.open = true; });
  }
  boxes.forEach(function (b) { b.addEventListener('change', apply); });
  search.addEventListener('input', apply);
})();
</script>"""

