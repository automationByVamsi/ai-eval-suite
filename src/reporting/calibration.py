"""
Judge calibration: do the LLM judges agree with a subject-matter expert (SME)?

  1. make review-sheet AGENT=knowledge_agent SUITE=golden [RUN=<run id>]
       writes outputs/review/<run id>.xlsx, a formatted workbook to share with the SMEs / POs:
         "How to review"  the run, what to do, and what each judge's pass mark is
         "Review"         one row per case: query type, business area, query, the agent's answer and
                          confidence, the expected answer, the pages (agent.yaml `review_columns:`, e.g.
                          anchor, supporting and evidence pages, each "id | title | link"), every judge's
                          score (green = passed, red = failed), the deterministic checks, and two
                          yellow columns for the SME:
                            SME verdict   pass | fail (drop-down)   is this answer good enough for a colleague?
                            SME notes     free text
  2. The SME fills the yellow columns (in Excel; keep it as .xlsx).
  3. make calibrate FILE=outputs/review/<run id>.xlsx
       per judge: how often it agrees with the SME, its false passes (judge passed an answer the SME
       failed — the dangerous kind) and false fails, and the threshold that would agree best.

Rows without an SME verdict, and judges that didn't score a row, are left out. Review sheets saved as
.csv by older versions still work with make calibrate.
"""

from __future__ import annotations

import csv
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


def review_sheet(run: Run, out: Path | None = None, columns: dict[str, str] | None = None) -> Path:
    """Write the SME review workbook for a run; returns its path. columns: extra {heading: field} to show."""
    judges = list(dict.fromkeys(r.name for c in run.cases for r in c.results if r.kind == "judge"))
    thresholds = {r.name: r.threshold for c in run.cases for r in c.results if r.kind == "judge" and r.threshold}
    columns = columns or {}
    reps = run.reps > 1
    header = [("Test case", "Case ID"), *([("Test case", "Run")] if reps else []),
              ("Test case", "Query type"), ("Test case", "Business area"), ("Test case", "Query"),
              ("Agent answer", "Agent answer"), ("Agent answer", "Confidence"), ("Agent answer", "Expected answer"),
              *[("Pages", heading) for heading in columns],
              *[("LLM judges", f"{_title(name)} (pass ≥ {thresholds.get(name, 0.7):g})") for name in judges],
              ("Result", "Deterministic checks"), ("Result", "Case result"),
              ("SME review", SME_VERDICT), ("SME review", SME_NOTES)]
    rows = []
    for case in run.cases:
        d, given = case.details or {}, case.input or {}
        by_name = {r.name: r for r in case.results if r.kind == "judge"}
        row = [case.case_id, *([case.rep + 1] if reps else []),
               given.get("question_type") or d.get("question_type") or "",
               given.get("business_area") or d.get("business_area") or "",
               case.question, case.answer, _confidence(d.get("confidence")), case.expected_answer]
        row += [_cell(d.get(field)) for field in columns.values()]
        row += [_score(by_name.get(name)) for name in judges]
        row += [_checks(case), Cell(case.status.upper(), "good" if case.status == PASS else "bad"),
                Cell("", "input"), Cell("", "input")]
        rows.append(row)
    verdict_column = len(header) - 1
    review = Sheet("Review", header, rows, freeze_columns=1, dropdowns={verdict_column: ["pass", "fail"]})
    out = out or paths.OUTPUTS_DIR / "review" / f"{run.run_id}.xlsx"
    write_xlsx(out, [_how_to(run, judges, thresholds), review])
    return out


def _how_to(run: Run, judges: list[str], thresholds: dict[str, float]) -> Sheet:
    """The first sheet: what was run, and what the reviewer is asked to do."""
    rows = [["Agent", run.agent], ["Suite", run.suite], ["Build", run.build or "-"], ["Run", run.run_id],
            ["Cases", len({c.case_id for c in run.cases})],
            ["What to do", "On the Review sheet, read each query, the agent's answer and the pages it used. "
                           "In the yellow columns, choose pass or fail (is this answer good enough to give a "
                           "colleague?) and add a note when it fails. Leave a row empty if unsure."],
            ["Judge scores", "0 to 1; green = the judge passed it, red = the judge failed it. "
                             "Your verdicts tell us whether the judges can be trusted."]]
    rows += [[f"{_title(name)}", f"passes at ≥ {thresholds.get(name, 0.7):g}"] for name in judges]
    return Sheet("How to review", [("", "Item"), ("", "Details")], rows)


def _score(result: Any) -> Any:
    """A judge's score, green when it passed and red when it failed; empty when it didn't score."""
    if result is None or result.status not in (PASS, FAIL) or result.score is None:
        return ""
    return Cell(round(result.score, 2), "good" if result.status == PASS else "bad")


def _checks(case: Any) -> str:
    """'8/9 passed' and, below it, the checks that failed (diagnostic ones marked)."""
    checks = [r for r in case.results if r.kind == "check" and r.status in (PASS, FAIL)]
    failed = [_title(r.name) + (" (diagnostic)" if r.diagnostic else "") for r in checks if r.status == FAIL]
    text = f"{len(checks) - len(failed)}/{len(checks)} passed" if checks else ""
    return text + ("\nFailed: " + ", ".join(failed) if failed else "")


def _confidence(value: Any) -> Any:
    tone = {"HIGH": "good", "LOW": "bad"}.get(str(value or "").upper(), "")
    return Cell(str(value).upper(), tone) if value else ""


def _title(name: str) -> str:
    """'context_recall' -> 'Context recall'."""
    return name.replace("_", " ").capitalize()


def _cell(value: Any) -> Any:
    """A field value for one cell: one list item per line; a record as "a | b | c" (e.g. id | title | link)."""
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
        pairs = []                                   # (score, sme_ok)
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
    """(rows with the SME verdict under "sme", {judge: (its score column, its threshold)}).
    Reads the .xlsx review sheet, or a .csv one from older versions (name_score / name_threshold columns)."""
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


def print_calibration(report: list[dict[str, Any]], sheet: Path) -> None:
    if not report:
        print(f"\nNo rows with an SME verdict (pass / fail) and a judge score in {sheet}\n")
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
    false_pass = sum(score >= threshold and not ok for score, ok in pairs)
    false_fail = sum(score < threshold and ok for score, ok in pairs)
    return {"agreement": 1 - (false_pass + false_fail) / len(pairs), "false_pass": false_pass,
            "false_fail": false_fail}
