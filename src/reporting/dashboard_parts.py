"""
The pieces of the results dashboard that aren't Streamlit calls: what an error means and how to fix
it, how a case's results split into judges and checks, and the small HTML blocks (cards, meters,
chips) the dashboard draws. No Streamlit here, so tests can check them without a browser.

Used by: every dashboard view (dashboard_run, dashboard_cases, dashboard_consistency, dashboard_verdict,
dashboard_verdict_parts) and tests/test_dashboard.py.
"""

from __future__ import annotations

import html
import json
import statistics
from typing import Any

from src.core.results import ERROR, FAIL, PASS, SKIP, CaseResult, Result, Run

STATUS_ICON = {PASS: "✓", FAIL: "✗", ERROR: "!", SKIP: "–"}
STATUS_WORD = {PASS: "Pass", FAIL: "Fail", ERROR: "Error", SKIP: "Skipped"}
SETUP_NAMES = ("lookup", "evidence_fetch")      # evidence_fetch: its name in runs saved before lookups
GROUP_TITLES = {"basic": "Basic", "setup": "Setup", "": "Other checks"}


# --- what went wrong, in plain words -----------------------------------------------------------

def problems(case: CaseResult) -> list[dict[str, str]]:
    """Every error in a case, explained: [{what, title, reason, hint}], the most serious first."""
    found = []
    if case.error:
        title, hint = explain_case_error(case.error)
        found.append({"what": "case", "title": title, "reason": case.error, "hint": hint})
    for result in case.results:
        if result.status == ERROR:
            title, hint = explain_result_error(result)
            found.append({"what": result.name, "title": title, "reason": result.reason, "hint": hint})
    return found


def explain_case_error(error: str) -> tuple[str, str]:
    """(title, how to fix) for CaseResult.error — the case could not be evaluated at all."""
    text = error.lower()
    if "no saved trace" in text:
        return ("No saved trace to replay",
                "OFFLINE=1 replays the last saved trace of each case. Run the case once without OFFLINE=1.")
    if text.startswith("agent:"):
        return ("The agent did not answer",
                "Check the agent is running at the connection.base_url in agent.yaml (make doctor), "
                "or raise connection.timeout_s if it is just slow.")
    if "required field" in text:
        return ("The trace format changed",
                "A required field in fields.yaml found nothing in the trace. Run the make fields command "
                "in the message to see which paths are out of date, and fix them in fields.yaml.")
    if text.startswith("parser"):
        return ("The agent's parser.py failed", "Fix parser.py: the message shows the exception it raised.")
    return ("The case could not be evaluated", "")


def explain_result_error(result: Result) -> tuple[str, str]:
    """(title, how to fix) for a check or judge that could not run."""
    if result.name in SETUP_NAMES:
        return ("A value could not be looked up outside the trace",
                "A function in the agent's lookups.py failed (the message names it and the id). Check its "
                "settings — usually credentials in env/.env — and the network. OFFLINE=1 still looks up ids "
                "it has never saved. Suites whose judges and checks don't read the field never look it up.")
    if result.kind == "judge":
        return (f"The {label(result.name)} judge could not score this case",
                "Usually the judge's own LLM call failed (credentials, network, rate limit): run make "
                "doctor. An error is never counted as a low score.")
    if result.name == "parser.checks":
        return ("The agent's parser.py checks failed", "Fix checks() in parser.py.")
    return (f"The {label(result.name)} check could not run", "")


# --- judges vs checks --------------------------------------------------------------------------

def split(case: CaseResult) -> tuple[list[Result], dict[str, list[Result]]]:
    """(judges, {group: checks}), in the order they ran. Setup errors are reported as problems instead."""
    judges = [r for r in case.results if r.kind == "judge"]
    groups: dict[str, list[Result]] = {}
    for r in case.results:
        if r.kind == "check" and not is_setup(r):
            groups.setdefault(r.group, []).append(r)
    return judges, groups


def is_setup(result: Result) -> bool:
    return result.group == "setup" or result.name in SETUP_NAMES


def tally(results: list[Result]) -> dict[str, int]:
    counts = {PASS: 0, FAIL: 0, ERROR: 0, SKIP: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def ran(counts: dict[str, int]) -> str:
    """'2/3' — passed out of those that gave a verdict (skips left out)."""
    judged = counts[PASS] + counts[FAIL] + counts[ERROR]
    return f"{counts[PASS]}/{judged}" if judged else "–"


def first_issue(case: CaseResult) -> str:
    """The one line that best says why a case did not pass."""
    if case.error:
        return explain_case_error(case.error)[0]
    for status in (ERROR, FAIL):
        for r in case.results:
            if r.status == status:
                if status == ERROR:
                    return explain_result_error(r)[0]
                score = f" ({r.score:.2f} < {r.threshold:.2f})" if r.score is not None and r.threshold else ""
                return f"{label(r.name)} failed{score}"
    return ""


def label(name: str) -> str:
    return name.replace("_", " ").replace(":", ": ").strip().capitalize()


# --- run-level numbers -------------------------------------------------------------------------

def run_stats(run: Run) -> dict[str, Any]:
    cases = run.cases
    results = [r for c in cases for r in c.results if not is_setup(r)]
    judges = tally([r for r in results if r.kind == "judge"])
    checks = tally([r for r in results if r.kind == "check"])
    scores = [r.score for r in results if r.kind == "judge" and r.score is not None]
    latencies = sorted(c.latency_ms for c in cases if c.latency_ms)
    return {
        "cases": len(cases),
        "passed": sum(c.status == PASS for c in cases),
        "failed": sum(c.status == FAIL for c in cases),
        "errors": sum(c.status == ERROR for c in cases),
        "judges": judges, "checks": checks,
        "judge_rate": rate(judges), "check_rate": rate(checks),
        "mean_score": statistics.fmean(scores) if scores else None,
        "median_s": statistics.median(latencies) / 1000 if latencies else None,
        "p95_s": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] / 1000 if latencies else None,
    }


def rate(counts: dict[str, int]) -> float | None:
    judged = counts[PASS] + counts[FAIL]
    return counts[PASS] / judged if judged else None


def pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def tone(value: float | None, good: float = 0.9, ok: float = 0.7) -> str:
    """good | warn | bad | muted — the colour of a rate."""
    if value is None:
        return "muted"
    return "good" if value >= good else "warn" if value >= ok else "bad"


# --- HTML pieces ---------------------------------------------------------------------------------

def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def chip(text: str, kind: str = "plain", title: str = "") -> str:
    tip = f' title="{esc(title)}"' if title else ""
    return f'<span class="chip {kind}"{tip}>{esc(text)}</span>'


def kpi(label_: str, value: str, sub: str = "", kind: str = "plain") -> str:
    return (f'<div class="kpi {kind}"><div class="kpi-label">{esc(label_)}</div>'
            f'<div class="kpi-value">{esc(value)}</div><div class="kpi-sub">{esc(sub)}</div></div>')


def bar(fraction: float | None, kind: str, marker: float | None = None) -> str:
    width = 0 if fraction is None else max(0.0, min(1.0, fraction)) * 100
    tick = (f'<div class="bar-marker" style="left:{max(0.0, min(1.0, marker)) * 100:.1f}%"></div>'
            if marker is not None else "")
    return f'<div class="bar"><div class="bar-fill {kind}" style="width:{width:.1f}%"></div>{tick}</div>'


def judge_html(result: Result) -> str:
    """One judge: name, engine, score against its threshold, and the judge's reason."""
    name = esc(label(result.name))
    engine = chip(result.engine, "ghost") if result.engine else ""
    reason = f'<div class="row-reason">{esc(result.reason)}</div>' if result.reason else ""
    if result.status in (PASS, FAIL) and result.score is not None:
        kind = "good" if result.status == PASS else "bad"
        threshold = f'<span class="muted"> / {result.threshold:.2f}</span>' if result.threshold is not None else ""
        return (f'<div class="judge"><div class="row-top"><span class="row-name">{name}</span>{engine}'
                f'<span class="score {kind}">{result.score:.2f}{threshold}</span></div>'
                f'{bar(result.score, kind, result.threshold)}{reason}</div>')
    kind = "warn" if result.status == ERROR else "muted"
    word = "could not score" if result.status == ERROR else "not run"
    return (f'<div class="judge {kind}"><div class="row-top"><span class="row-name">{name}</span>{engine}'
            f'<span class="score {kind}">{word}</span></div>{reason}</div>')


def check_html(result: Result) -> str:
    kind = {PASS: "good", FAIL: "bad", ERROR: "warn", SKIP: "muted"}[result.status]
    score = (f' <span class="muted">{result.score:.2f} / {result.threshold:.2f}</span>'
             if result.score is not None and result.threshold is not None else "")
    reason = f'<div class="row-reason">{esc(result.reason)}</div>' if result.reason else ""
    return (f'<div class="check"><span class="icon {kind}">{STATUS_ICON[result.status]}</span>'
            f'<div><div class="row-name">{esc(label(result.name))}{score}</div>{reason}</div></div>')


def checks_html(groups: dict[str, list[Result]]) -> str:
    """Checks by group: failures and errors in full, passes as compact chips, skips folded away."""
    parts = []
    for group, results in groups.items():
        counts = tally(results)
        loud = [r for r in results if r.status in (FAIL, ERROR)]
        passed = [r for r in results if r.status == PASS]
        skipped = [r for r in results if r.status == SKIP]
        state = f"{ran(counts)} passed" if len(skipped) < len(results) else "all skipped"
        head = (f'<div class="group-head"><span>{esc(GROUP_TITLES.get(group, group.capitalize()))}</span>'
                f'<span class="muted">{state}</span></div>')
        body = "".join(check_html(r) for r in loud)
        if passed:
            body += '<div class="chips">' + "".join(
                chip("✓ " + label(r.name), "good-soft", r.reason or "passed") for r in passed) + "</div>"
        if skipped:
            body += (f'<details class="skips"><summary>{len(skipped)} skipped — why</summary>'
                     + "".join(check_html(r) for r in skipped) + "</details>")
        parts.append(f'<div class="group">{head}{body}</div>')
    return "".join(parts)


def problem_html(problem: dict[str, str]) -> str:
    hint = f'<div class="problem-hint"><b>How to fix:</b> {esc(problem["hint"])}</div>' if problem["hint"] else ""
    where = "" if problem["what"] == "case" else f'<span class="chip ghost">{esc(problem["what"])}</span>'
    return (f'<div class="problem"><div class="problem-title">⚠ {esc(problem["title"])} {where}</div>'
            f'<div class="problem-reason">{esc(problem["reason"])}</div>{hint}</div>')


def scoreboard_html(rows: list[dict[str, Any]], kind: str, show_group: bool = True) -> str:
    """Per judge / check across the run: pass rate bar, mean score and counts (rows from summarise)."""
    out = []
    for row in rows:
        if row["kind"] != kind or row["name"] in SETUP_NAMES:
            continue
        counts = "".join(chip(f"{row[s]} {STATUS_WORD[s].lower()}", c) for s, c in
                         ((FAIL, "bad-soft"), (ERROR, "warn-soft"), (SKIP, "ghost")) if row[s])
        mean = f' · mean {row["mean_score"]:.2f}' if row.get("mean_score") is not None and kind == "judge" else ""
        judged = row[PASS] + row[FAIL]
        value = (f'{pct(row["rate"])} <span class="muted">({row[PASS]}/{judged}{mean})</span>'
                 if row["rate"] is not None else '<span class="muted">never ran</span>')
        group = (chip(GROUP_TITLES.get(row.get("group", ""), row.get("group", "")), "ghost")
                 if kind == "check" and show_group else "")
        unstable = (chip(f'{len(row["unstable"])} unstable', "warn-soft", ", ".join(row["unstable"]))
                    if row.get("unstable") else "")
        out.append(f'<div class="sb-row"><div class="row-top"><span class="row-name">{esc(label(row["name"]))}</span>'
                   f'{group}<span class="score {tone(row["rate"])}">{value}</span></div>'
                   f'{bar(row["rate"], tone(row["rate"]))}<div class="chips">{counts}{unstable}</div></div>')
    return "".join(out) or '<div class="muted">None in this run.</div>'


def check_scoreboard_html(rows: list[dict[str, Any]]) -> str:
    """Checks across the run, by group: the ones that ever failed get a full row, the rest are chips."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["kind"] == "check" and row["name"] not in SETUP_NAMES:
            groups.setdefault(row.get("group", ""), []).append(row)
    out = []
    for group, members in groups.items():
        passes = sum(r[PASS] for r in members)
        judged = passes + sum(r[FAIL] for r in members)
        group_rate = passes / judged if judged else None
        loud = [r for r in members if r[FAIL] or r[ERROR]]
        clean = [r for r in members if not (r[FAIL] or r[ERROR]) and r["rate"] is not None]
        never = [r for r in members if r["rate"] is None and not r[ERROR]]
        body = scoreboard_html(loud, "check", show_group=False) if loud else ""
        if clean:
            body += '<div class="chips">' + "".join(
                chip(f"✓ {label(r['name'])} {r[PASS]}/{r[PASS] + r[FAIL]}", "good-soft") for r in clean) + "</div>"
        if never:
            body += '<div class="chips">' + "".join(
                chip(f"– {label(r['name'])}", "ghost", "skipped in every case: no expected data, or its when: "
                     "never held") for r in never) + "</div>"
        title = esc(GROUP_TITLES.get(group, group.capitalize()))
        out.append(f'<div class="group"><div class="group-head"><span>{title}</span>'
                   f'<span class="score {tone(group_rate)}">{pct(group_rate)}</span></div>'
                   f'{body}</div>')
    return "".join(out) or '<div class="muted">This suite runs no deterministic checks.</div>'


def targets_html(rows: list[dict[str, Any]]) -> str:
    """Release targets: actual vs target, with a bar and a met / missed / n/a chip."""
    out = []
    for r in rows:
        kind = {True: "good", False: "bad", None: "muted"}[r["met"]]
        word = {True: "met", False: "missed", None: "n/a"}[r["met"]]
        sign = "≤" if r["ceiling"] else "≥"
        actual = "–" if r["actual"] is None else f"{r['actual']:.0%}"
        out.append(f'<div class="sb-row"><div class="row-top"><span class="row-name">{esc(label(r["name"]))}</span>'
                   f'{chip(word, kind + "-soft" if kind != "muted" else "ghost")}'
                   f'<span class="score {kind}">{actual} <span class="muted">target {sign} {r["target"]:.0%}</span>'
                   f'</span></div>{bar(r["actual"], kind, None if r["ceiling"] else r["target"])}'
                   f'<div class="row-reason">{esc(r["detail"])}</div></div>')
    return "".join(out)


# --- the pages behind an answer ----------------------------------------------------------------

def evidence_pages(case: CaseResult) -> list[dict[str, Any]]:
    """
    The pages the agent used, from the conventional fields.yaml names (evidence_page_ids,
    evidence_titles, contexts, anchor_page_ids, expanded_page_ids, cited_page_ids), each marked with
    its role. Agents without these fields get their contexts listed as plain passages.
    """
    d = case.details or {}
    ids = [str(i) for i in _list(d.get("evidence_page_ids"))]
    titles = _list(d.get("evidence_titles"))
    texts = _list(d.get("contexts"))
    anchors = {str(i) for i in _list(d.get("anchor_page_ids"))}
    expanded = {str(i) for i in _list(d.get("expanded_page_ids"))}
    cited = {str(i) for i in _list(d.get("cited_page_ids"))}
    expected = {str(i) for i in _list(case.expected.get("expected_anchor_page_ids"))
                + _list(case.expected.get("expected_related_page_ids"))}
    if not ids:
        return [{"id": "", "title": f"Passage {n + 1}", "text": str(t), "roles": []} for n, t in enumerate(texts)]
    pages = []
    for n, page_id in enumerate(ids):
        roles = [role for role, ids_ in (("anchor", anchors), ("expanded", expanded), ("cited", cited),
                                          ("expected", expected)) if page_id in ids_]
        pages.append({"id": page_id, "title": str(titles[n]) if n < len(titles) else f"Page {page_id}",
                      "text": str(texts[n]) if len(texts) == len(ids) else "", "roles": roles})
    return pages


def expected_pages_missed(case: CaseResult) -> list[str]:
    """Expected page ids / titles that are nowhere in the evidence (a retrieval miss)."""
    d = case.details or {}
    have = {_norm(x) for x in _list(d.get("evidence_page_ids")) + _list(d.get("evidence_titles"))}
    want = [x for key in ("expected_anchor_page_ids", "expected_anchor_page_titles",
                          "expected_related_page_ids", "expected_related_page_titles")
            for x in _list(case.expected.get(key))]
    return [str(w) for w in want if _norm(w) not in have] if have else []


def page_html(page: dict[str, Any]) -> str:
    roles = "".join(chip(r, {"anchor": "accent", "cited": "good-soft", "expected": "warn-soft"}.get(r, "ghost"))
                    for r in page["roles"])
    pid = f'<span class="muted mono">#{esc(page["id"])}</span>' if page["id"] else ""
    head = f'<span class="page-title">{esc(page["title"])}</span> {pid} {roles}'
    if not page["text"]:
        return f'<div class="page">{head}</div>'
    return (f'<details class="page"><summary>{head}</summary>'
            f'<div class="page-text">{esc(page["text"][:3000])}</div></details>')


# --- consistency: the same case over several runs ---------------------------------------------

def pages_by_run(reps: list[CaseResult]) -> list[dict[str, Any]]:
    """
    One row per page used in any run: its title, and per run its roles (anchor / expanded / cited, or
    "used" when it's only in the evidence list; "" when that run didn't use it). Pages used in every run
    first; `differs` marks a page that is missing from a run or whose anchor role changes.
    """
    order: dict[str, dict[str, Any]] = {}
    per_run: list[dict[str, list[str]]] = []
    for case in reps:
        d = case.details or {}
        roles: dict[str, list[str]] = {}
        for page in evidence_pages(case):
            if page["id"]:
                roles[page["id"]] = [r for r in page["roles"] if r != "expected"] or ["used"]
                order.setdefault(page["id"], {"title": page["title"]})
                if order[page["id"]]["title"] == f"Page {page['id']}":
                    order[page["id"]]["title"] = page["title"]
        for role, key in (("anchor", "anchor_page_ids"), ("cited", "cited_page_ids")):   # not in the evidence list
            for page_id in (str(i) for i in _list(d.get(key))):
                if page_id not in roles:
                    roles[page_id] = [role]
                    order.setdefault(page_id, {"title": f"Page {page_id}"})
                elif role not in roles[page_id]:
                    roles[page_id] = [r for r in roles[page_id] if r != "used"] + [role]
        per_run.append(roles)
    expected = {str(i) for c in reps[:1] for key in ("expected_anchor_page_ids", "expected_related_page_ids")
                for i in _list(c.expected.get(key))}
    rows = []
    for position, (page_id, info) in enumerate(order.items()):
        cells = [run.get(page_id, []) for run in per_run]
        used = sum(bool(c) for c in cells)
        anchors = sum("anchor" in c for c in cells)
        rows.append({"id": page_id, "title": info["title"], "expected": page_id in expected, "runs": cells,
                     "used_in": used, "differs": used != len(cells) or anchors not in (0, len(cells)),
                     "_order": (used != len(cells), -anchors, -used, position)})
    rows.sort(key=lambda r: r["_order"])
    return rows


def pages_grid_html(rows: list[dict[str, Any]], reps: int) -> str:
    """The pages x runs table: a row per page, a column per run, roles as chips; changing rows tinted."""
    kinds = {"anchor": "accent", "cited": "good-soft", "expanded": "ghost", "used": "ghost"}
    head = "".join(f"<th>Run {n + 1}</th>" for n in range(reps))
    body = []
    for row in rows:
        cells = "".join(
            "<td>" + ("".join(chip(role, kinds.get(role, "ghost")) for role in roles) if roles
                      else '<span class="absent">not used</span>') + "</td>"
            for roles in row["runs"])
        tag = chip("expected", "warn-soft") if row["expected"] else ""
        body.append(f'<tr class="{"differs" if row["differs"] else ""}"><td class="page-cell">'
                    f'<span class="page-title">{esc(row["title"])}</span> '
                    f'<span class="muted mono">#{esc(row["id"])}</span> {tag}'
                    f'<div class="row-reason">in {row["used_in"]} of {reps} runs</div></td>{cells}</tr>')
    return (f'<div class="grid-wrap"><table class="grid"><thead><tr><th>Page</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def short(value: Any, width: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def as_list(value: Any) -> list[Any]:
    """None / "" -> [], a single value -> [value], a list -> itself."""
    return _list(value)


def _list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _norm(value: Any) -> str:
    return " ".join(str(value).casefold().split())
