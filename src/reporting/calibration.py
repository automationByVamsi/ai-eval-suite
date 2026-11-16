"""Judge calibration: write an SME review workbook for a run, then measure how well each LLM judge agrees with it.

Older .csv review sheets are still accepted by calibrate.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from src.core import paths
from src.core.results import FAIL, PASS, Run
from src.exporters.xlsx import Cell, Sheet, write_xlsx
from src.importers.spreadsheet import read_rows

SME_PASS = {"pass", "p", "yes", "y", "good", "ok", "correct", "1", "true"}
SME_FAIL = {"fail", "f", "no", "n", "bad", "wrong", "incorrect", "0", "false"}
SME_VERDICT, SME_NOTES = "SME verdict (pass / fail)", "SME notes"
JUDGE_HEADER = re.compile(r"^(?P<name>.+) \(pass ≥ (?P<threshold>[0-9.]+)\)$")     # "Faithfulness (pass ≥ 0.7)"


# Columns when the agent has no exporters/review_sheet.yaml: {group: {heading: value}}.
BASIC_COLUMNS = {"Test case": {"Query": "case.question"},
                 "Agent answer": {"Agent answer": "case.answer", "Expected answer": "case.expected_answer"}}
TONE = {"green": "good", "red": "bad"}


def review_sheet(run: Run, out: Path | None = None, columns: dict[str, dict] | None = None) -> Path:
    """Write the SME review workbook for a run; returns its path.
    columns: {group: {heading: value}} from exporters/review_sheet.yaml (see the knowledge_agent one)."""
    judges = list(dict.fromkeys(r.name for c in run.cases for r in c.results if r.kind == "judge"))
    thresholds = {r.name: r.threshold for c in run.cases for r in c.results if r.kind == "judge" and r.threshold}
    shown = [(group, heading, value) for group, headings in (columns or BASIC_COLUMNS).items()
             for heading, value in headings.items()]
    reps = run.reps > 1
    header = [("Test case", "Case ID"), *([("Test case", "Run")] if reps else []),
              *[(group, heading) for group, heading, _ in shown],
              *[("LLM judges", f"{_title(name)} (pass ≥ {thresholds.get(name, 0.7):g})") for name in judges],
              ("Result", "Deterministic checks"), ("Result", "Case result"),
              ("SME review", SME_VERDICT), ("SME review", SME_NOTES),
              ("Reference", "Agent output (raw)")]
    rows = []
    for case in run.cases:
        by_name = {r.name: r for r in case.results if r.kind == "judge"}
        row = [case.case_id, *([case.rep + 1] if reps else [])]
        row += [_column(case, value) for _, _, value in shown]
        row += [_score(by_name.get(name)) for name in judges]
        row += [_checks(case), Cell(case.status.upper(), "good" if case.status == PASS else "bad"),
                Cell("", "input"), Cell("", "input"), _raw((case.details or {}).get("agent_response"))]
        rows.append(row)
    verdict_column = header.index(("SME review", SME_VERDICT))
    review = Sheet("Review", header, rows, freeze_columns=1, dropdowns={verdict_column: ["pass", "fail"]})
    out = out or paths.OUTPUTS_DIR / "review" / f"{run.run_id}.xlsx"
    write_xlsx(out, [_how_to(run, judges, thresholds), review])
    return out


def _column(case: Any, value: Any) -> Any:
    """One configured cell: the first non-empty source, coloured when `colours:` matches its text."""
    if isinstance(value, dict):
        cell = _column(case, value["value"])
        for text, colour in (value.get("colours") or {}).items():
            if str(cell).strip().lower() == str(text).lower():
                return Cell(str(text), TONE[colour])
        return cell
    for source in value if isinstance(value, list) else [value]:
        cell = _cell(_source(case, str(source)))
        if cell not in ("", None, []):
            return cell
    return ""


def _source(case: Any, source: str) -> Any:
    """A column value: case.question / case.answer / case.expected_answer, input.<key>, or a field."""
    details = case.details or {}
    if source == "case.answer":
        return case.answer or _refusal(details)
    if source.startswith("case."):
        return getattr(case, source.removeprefix("case."), "")
    if source.startswith("input."):
        return (case.input or {}).get(source.removeprefix("input."))
    return details.get(source)


def _how_to(run: Run, judges: list[str], thresholds: dict[str, float]) -> Sheet:
    """Build the "How to review" sheet: what was run and what the reviewer should do."""
    rows = [["Agent", run.agent], ["Suite", run.suite], ["Build", run.build or "-"], ["Run", run.run_id],
            ["Cases", len({c.case_id for c in run.cases})],
            ["What to do", "On the Review sheet, read each query, the agent's answer and the pages it used. "
                           "In the yellow columns, choose pass or fail (is this answer good enough to give a "
                           "colleague?) and add a note when it fails. Leave a row empty if unsure."],
            ["Judge scores", "0 to 1; green = the judge passed it, red = the judge failed it. "
                             "Your verdicts tell us whether the judges can be trusted."]]
    rows += [[f"{_title(name)}", f"passes at ≥ {thresholds.get(name, 0.7):g}"] for name in judges]
    return Sheet("How to review", [("", "Item"), ("", "Details")], rows)


def _refusal(details: dict[str, Any]) -> str:
    """What the colleague gets when the agent refuses instead of answering."""
    return f"(no answer — the agent returned an error: {details['agent_error']})" if details.get("agent_error") else ""


def _raw(value: Any) -> str:
    """The agent's whole final output as JSON, exactly as returned (capped for Excel's cell limit)."""
    if value in (None, "", {}):
        return ""
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return text[:30000]


def _score(result: Any) -> Any:
    """Return a judge's score cell (green = passed, red = failed), or "" when it didn't score."""
    if result is None or result.status not in (PASS, FAIL) or result.score is None:
        return ""
    return Cell(round(result.score, 2), "good" if result.status == PASS else "bad")


def _checks(case: Any) -> str:
    """Return "8/9 passed" plus a line listing the failed checks (diagnostic ones marked)."""
    checks = [r for r in case.results if r.kind == "check" and r.status in (PASS, FAIL)]
    failed = [_title(r.name) + (" (diagnostic)" if r.diagnostic else "") for r in checks if r.status == FAIL]
    text = f"{len(checks) - len(failed)}/{len(checks)} passed" if checks else ""
    return text + ("\nFailed: " + ", ".join(failed) if failed else "")


def _title(name: str) -> str:
    """Turn a field name into a title: 'context_recall' -> 'Context recall'."""
    return name.replace("_", " ").capitalize()


def _cell(value: Any) -> Any:
    """Format a field value for one cell: lists one item per line, records as "a | b | c"."""
    if isinstance(value, list):
        return "\n".join(str(_cell(v)) for v in value)
    if isinstance(value, dict):
        return " | ".join(str(v) for v in value.values())
    return "" if value is None else value


def calibrate(sheet: Path) -> list[dict[str, Any]]:
    """Per judge: n, agreement, false passes, false fails, and the best-agreeing threshold."""
    rows, judges = _read_review(Path(sheet))
    report = []
    for name, (score_column, threshold) in judges.items():
        pairs = []  # (score, sme_ok)
        for row in rows:
            sme = str(row.get("sme") or "").strip().lower()
            score = str(row.get(score_column) or "").strip()
            if sme in SME_PASS | SME_FAIL and score:
                pairs.append((float(score), sme in SME_PASS))
        if not pairs:
            continue
        stats = _agreement(pairs, threshold)
        candidates = [t / 100 for t in range(5, 100, 5)]
        best = max(candidates, key=lambda t: (_agreement(pairs, t)["agreement"], -abs(t - threshold)))
        report.append({"judge": name, "n": len(pairs), "threshold": threshold, **stats,
                       "best_threshold": best, "best_agreement": _agreement(pairs, best)["agreement"]})
    return report


def _read_review(sheet: Path) -> tuple[list[dict[str, Any]], dict[str, tuple[str, float]]]:
    """Read a review sheet (.xlsx, or older .csv) into (rows with the SME verdict as "sme",
    {judge: (score column, threshold)})."""
    if sheet.suffix.lower() == ".xlsx":
        rows = read_rows(sheet, sheet="Review", header_row=2)
        judges = {}
        for header in rows[0] if rows else []:
            found = JUDGE_HEADER.match(header)
            if found:
                judges[found["name"].lower().replace(" ", "_")] = (header, float(found["threshold"]))
        return [{**r, "sme": r.get(SME_VERDICT)} for r in rows], judges
    with sheet.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    judges = {}
    for header in rows[0] if rows else []:
        if header.endswith("_score"):
            name = header[: -len("_score")]
            threshold = next((r[f"{name}_threshold"] for r in rows if r.get(f"{name}_threshold")), 0.7)
            judges[name] = (header, float(threshold))
    return [{**r, "sme": r.get("sme_verdict")} for r in rows], judges


def why_empty(sheet: Path) -> str:
    """Explain in one line why a review sheet had nothing to compare."""
    rows, judges = _read_review(Path(sheet))
    marked = [r for r in rows if str(r.get("sme") or "").strip().lower() in SME_PASS | SME_FAIL]
    if not judges:
        return ("the sheet has no LLM judge scores — the run was made without judges (JUDGES=0, or a suite "
                "with no metrics). Run the suite with judges, then make review-sheet again.")
    if not marked:
        typed = sorted({str(r.get("sme")) for r in rows if str(r.get("sme") or "").strip()})
        return ("no row has an SME verdict of pass / fail" + (f" (found: {typed})" if typed else "")
                + f" — is this the file the SME saved, and is the column still '{SME_VERDICT}'?")
    return f"{len(marked)} row(s) have an SME verdict, but none of them has a judge score (judges skipped or errored)."


def print_calibration(report: list[dict[str, Any]], sheet: Path) -> None:
    """Print the judge-vs-SME table, or why there was nothing to compare."""
    if not report:
        print(f"\nNothing to compare in {sheet}:\n  {why_empty(sheet)}\n")
        return
    print(f"\nJudge vs SME ({sheet})")
    print("-" * 96)
    print(f"  {'judge':<22} {'n':>3}  {'agree':>6}  {'false pass':>10}  {'false fail':>10}  "
          f"{'threshold':>9}  {'best threshold (agree)':>22}")
    for r in report:
        print(f"  {r['judge']:<22} {r['n']:>3}  {r['agreement']:>6.0%}  {r['false_pass']:>10}  {r['false_fail']:>10}  "
              f"{r['threshold']:>9.2f}  {r['best_threshold']:>14.2f} ({r['best_agreement']:.0%})")
    print("\n  false pass = the judge passed an answer the SME failed (the costly mistake).")
    print("  Change a threshold in agent.yaml only with enough rows (20+) and a clear gain.\n")


def _agreement(pairs: list[tuple[float, bool]], threshold: float) -> dict[str, Any]:
    """Return agreement rate, false passes and false fails for (score, sme_ok) pairs at a threshold."""
    false_pass = sum(score >= threshold and not ok for score, ok in pairs)
    false_fail = sum(score < threshold and ok for score, ok in pairs)
    return {"agreement": 1 - (false_pass + false_fail) / len(pairs), "false_pass": false_pass,
            "false_fail": false_fail}
