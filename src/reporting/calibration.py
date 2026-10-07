"""
Judge calibration: do the LLM judges agree with a subject-matter expert (SME)?

  1. make review-sheet AGENT=knowledge_agent SUITE=golden [RUN=<run id>]
       writes outputs/review/<run id>.csv: one row per case — question, agent answer, expected
       answer, the agent's `review_columns:` (agent.yaml, e.g. its anchor and related pages),
       every judge's score and verdict, and two empty columns for the SME:
         sme_verdict   pass | fail      (is this answer good enough to give a colleague?)
         sme_notes     free text
  2. The SME fills sme_verdict (in Excel; keep it as CSV).
  3. make calibrate FILE=outputs/review/<run id>.csv
       per judge: how often it agrees with the SME, its false passes (judge passed an answer the SME
       failed — the dangerous kind) and false fails, and the threshold that would agree best.

Rows without an sme_verdict, and judges that didn't score a row, are left out.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.core import paths
from src.core.results import FAIL, PASS, Run

SME_PASS = {"pass", "p", "yes", "y", "good", "ok", "correct", "1", "true"}
SME_FAIL = {"fail", "f", "no", "n", "bad", "wrong", "incorrect", "0", "false"}


def review_sheet(run: Run, out: Path | None = None, columns: dict[str, str] | None = None) -> Path:
    """Write the SME review CSV for a run; returns its path. columns: extra {heading: field} to show."""
    judges = list(dict.fromkeys(r.name for c in run.cases for r in c.results if r.kind == "judge"))
    out = out or paths.OUTPUTS_DIR / "review" / f"{run.run_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or {}
    header = ["run_id", "case_id", "rep", "question", "agent_answer", "expected_answer", *columns]
    for name in judges:
        header += [f"{name}_score", f"{name}_verdict", f"{name}_threshold"]
    header += ["sme_verdict", "sme_notes"]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for case in run.cases:
            by_name = {r.name: r for r in case.results if r.kind == "judge"}
            row = [run.run_id, case.case_id, case.rep + 1, case.question, case.answer, case.expected_answer]
            row += [_cell((case.details or {}).get(name)) for name in columns.values()]
            for name in judges:
                r = by_name.get(name)
                scored = r is not None and r.status in (PASS, FAIL)
                row += [r.score if scored else "", r.status if scored else "", r.threshold if r else ""]
            writer.writerow(row + ["", ""])
    return out


def _cell(value: Any) -> Any:
    """A field value for one CSV cell: one list item per line; a record as "a | b | c" (e.g. id | title | link)."""
    if isinstance(value, list):
        return "\n".join(str(_cell(v)) for v in value)
    if isinstance(value, dict):
        return " | ".join(str(v) for v in value.values())
    return "" if value is None else value


def calibrate(sheet: Path) -> list[dict[str, Any]]:
    """Per judge: n, agreement, false passes, false fails, and the best-agreeing threshold."""
    with Path(sheet).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    judges = [h[: -len("_score")] for h in (rows[0].keys() if rows else []) if h.endswith("_score")]
    report = []
    for name in judges:
        pairs = []                                   # (score, sme_ok)
        for row in rows:
            sme = (row.get("sme_verdict") or "").strip().lower()
            score = (row.get(f"{name}_score") or "").strip()
            if sme in SME_PASS | SME_FAIL and score:
                pairs.append((float(score), sme in SME_PASS))
        if not pairs:
            continue
        threshold = float(next((r[f"{name}_threshold"] for r in rows if r.get(f"{name}_threshold")), 0.7))
        stats = _agreement(pairs, threshold)
        candidates = [t / 100 for t in range(5, 100, 5)]
        best = max(candidates, key=lambda t: (_agreement(pairs, t)["agreement"], -abs(t - threshold)))
        report.append({"judge": name, "n": len(pairs), "threshold": threshold, **stats,
                       "best_threshold": best, "best_agreement": _agreement(pairs, best)["agreement"]})
    return report


def print_calibration(report: list[dict[str, Any]], sheet: Path) -> None:
    if not report:
        print(f"\nNo rows with an sme_verdict (pass / fail) and a judge score in {sheet}\n")
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
