"""
Excel export for evaluation dashboard results (PO-friendly workbook).

Consumes the same CaseEvaluationResult / E2ECaseResult models written by
publish_suite_result() — no Streamlit dependency.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.models.evaluation_result import CaseEvaluationResult, E2ECaseResult

# Dashboard palette (light theme)
_HEADER_FILL = PatternFill("solid", fgColor="F4F4F2")
_PASS_FILL = PatternFill("solid", fgColor="E8F7E8")
_FAIL_FILL = PatternFill("solid", fgColor="FDECEC")
_PASS_FONT = Font(color="0CA30C", bold=True)
_FAIL_FONT = Font(color="D03B3B", bold=True)
_HEADER_FONT = Font(bold=True)
_THIN_BORDER = Border(
    left=Side(style="thin", color="E1E0D9"),
    right=Side(style="thin", color="E1E0D9"),
    top=Side(style="thin", color="E1E0D9"),
    bottom=Side(style="thin", color="E1E0D9"),
)

_ANSWER_TRUNCATE = 500
_REASON_TRUNCATE = 300

_RESULT_FIELD_COLUMNS = (
    "rewritten_query",
    "anchor_page_id",
    "business_area",
    "decision",
    "golden_source",
    "source_page_id",
    "synthesis_style",
)


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "–"
    return f"{100 * numerator / denominator:.0f}%"


def _status_label(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _flatten_stage_rows(
    stage_results: Iterable[CaseEvaluationResult],
) -> list[CaseEvaluationResult]:
    return list(stage_results)


def _stages_from_e2e(e2e_results: Iterable[E2ECaseResult]) -> list[CaseEvaluationResult]:
    rows: list[CaseEvaluationResult] = []
    for e2e in e2e_results:
        rows.extend(e2e.stages)
    return rows


def _answer_from_e2e(e2e: E2ECaseResult) -> str:
    for stage in reversed(e2e.stages):
        if (stage.answer or "").strip():
            return stage.answer
    return ""


def _expected_from_e2e(e2e: E2ECaseResult) -> str:
    for stage in e2e.stages:
        if (stage.expected_output or "").strip():
            return stage.expected_output
    return ""


def _failure_reason(result: CaseEvaluationResult) -> str:
    reasons = result.failed_reasons
    if not reasons:
        return ""
    return _truncate("; ".join(reasons), _REASON_TRUNCATE)


def _field_values(result_fields: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _RESULT_FIELD_COLUMNS:
        value = result_fields.get(key)
        if value is None or value == "":
            out[key] = ""
        else:
            out[key] = _truncate(str(value), 200)
    return out


def _style_header_row(ws: Worksheet, *, row: int = 1) -> None:
    for cell in ws[row]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _THIN_BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _auto_width(ws: Worksheet, *, min_width: int = 10, max_width: int = 48) -> None:
    for col_idx, column_cells in enumerate(ws.columns, start=1):
        letter = get_column_letter(col_idx)
        max_len = 0
        for cell in column_cells:
            if cell.value is None:
                continue
            max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max(max_len + 2, min_width), max_width)


def _write_kv_block(ws: Worksheet, rows: list[tuple[str, str]], *, start_row: int = 1) -> int:
    row = start_row
    for label, value in rows:
        ws.cell(row=row, column=1, value=label).font = _HEADER_FONT
        ws.cell(row=row, column=2, value=value)
        row += 1
    return row


def _write_executive_summary(
    ws: Worksheet,
    *,
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
    scope_label: str,
    run_id: str,
) -> None:
    ws.title = "Executive Summary"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if view_mode == "e2e" and e2e_results:
        cases = len(e2e_results)
        passed = sum(1 for r in e2e_results if r.passed)
        stage_rows = _stages_from_e2e(e2e_results)
    else:
        cases = len(stage_results)
        passed = sum(1 for r in stage_results if r.passed)
        stage_rows = stage_results

    det_total = sum(len(r.deterministic_results) for r in stage_rows)
    det_passed = sum(sum(c.passed for c in r.deterministic_results) for r in stage_rows)
    judge_total = sum(len(r.metric_results) for r in stage_rows)
    judge_passed = sum(sum(m.passed for m in r.metric_results) for r in stage_rows)
    latencies = [
        r.latency_ms
        for r in (e2e_results if view_mode == "e2e" and e2e_results else stage_results)
        if r.latency_ms
    ]
    avg_latency = f"{(sum(latencies) / len(latencies) / 1000):.1f}s" if latencies else "–"

    agents = sorted(
        {
            r.agent_name
            for r in (e2e_results if view_mode == "e2e" and e2e_results else stage_results)
            if r.agent_name
        }
    )
    suites = sorted({r.eval_name for r in stage_rows if r.eval_name})

    next_row = _write_kv_block(
        ws,
        [
            ("Report generated", generated_at),
            ("Scope", scope_label),
            ("Run ID", run_id or "–"),
            ("View", view_mode),
            ("Agents", ", ".join(agents) if agents else "–"),
            ("Suites / stages", ", ".join(suites) if suites else "–"),
            ("Test cases", str(cases)),
            ("Overall pass rate", _pct(passed, cases)),
            ("Deterministic checks", _pct(det_passed, det_total)),
            ("Judge checks", _pct(judge_passed, judge_total) if judge_total else "–"),
            ("Average latency", avg_latency),
        ],
    )
    ws.cell(row=next_row + 1, column=1, value="Note").font = _HEADER_FONT
    ws.cell(
        row=next_row + 1,
        column=2,
        value=(
            "Metrics catalogue and thresholds are illustrative for demo purposes. "
            "Synthesized goldens should be reviewed separately from SME-curated cases."
        ),
    ).alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 72


def _apply_status_style(cell, passed: bool) -> None:
    cell.font = _PASS_FONT if passed else _FAIL_FONT
    cell.fill = _PASS_FILL if passed else _FAIL_FILL


def _write_test_results_sheet(
    ws: Worksheet,
    *,
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
) -> None:
    ws.title = "Test Results"
    base_headers = [
        "Test Case ID",
        "Agent",
        "Suite / Stage",
        "Run ID",
        "Status",
        "Question",
        "Answer",
        "Expected / Golden",
        "Failure Reason",
        "Latency (s)",
        "Det Passed",
        "Det Total",
        "Judge Passed",
        "Judge Total",
    ]
    field_headers = list(_RESULT_FIELD_COLUMNS)
    headers = base_headers + field_headers

    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    _style_header_row(ws)

    row = 2
    if view_mode == "e2e" and e2e_results:
        for e2e in sorted(e2e_results, key=lambda r: (r.agent_name, r.test_case_id)):
            stage_rows = e2e.stages
            det_passed = sum(sum(c.passed for c in s.deterministic_results) for s in stage_rows)
            det_total = sum(len(s.deterministic_results) for s in stage_rows)
            judge_passed = sum(sum(m.passed for m in s.metric_results) for s in stage_rows)
            judge_total = sum(len(s.metric_results) for s in stage_rows)
            merged_fields: dict[str, Any] = {}
            for s in stage_rows:
                merged_fields.update(s.result_fields)
            fields = _field_values(merged_fields)
            failed_stage = next((s for s in stage_rows if not s.passed), None)
            failure = _failure_reason(failed_stage) if failed_stage else ""

            values = [
                e2e.test_case_id,
                e2e.agent_name,
                f"e2e ({len(stage_rows)} stages)",
                e2e.run_id,
                _status_label(e2e.passed),
                e2e.question,
                _truncate(_answer_from_e2e(e2e), _ANSWER_TRUNCATE),
                _truncate(_expected_from_e2e(e2e), _ANSWER_TRUNCATE),
                failure,
                f"{e2e.latency_ms / 1000:.1f}" if e2e.latency_ms else "",
                det_passed,
                det_total,
                judge_passed,
                judge_total,
            ] + [fields[h] for h in field_headers]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN_BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=col in {6, 7, 8, 9})
                if col == 5:
                    _apply_status_style(cell, e2e.passed)
            row += 1
    else:
        for result in sorted(
            stage_results, key=lambda r: (r.agent_name, r.test_case_id, r.eval_name)
        ):
            det_passed = sum(c.passed for c in result.deterministic_results)
            judge_passed = sum(m.passed for m in result.metric_results)
            fields = _field_values(result.result_fields)
            values = [
                result.test_case_id,
                result.agent_name,
                result.eval_name,
                result.run_id,
                _status_label(result.passed),
                result.question,
                _truncate(result.answer, _ANSWER_TRUNCATE),
                _truncate(result.expected_output, _ANSWER_TRUNCATE),
                _failure_reason(result),
                f"{result.latency_ms / 1000:.1f}" if result.latency_ms else "",
                det_passed,
                len(result.deterministic_results),
                judge_passed,
                len(result.metric_results),
            ] + [fields[h] for h in field_headers]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN_BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=col in {6, 7, 8, 9})
                if col == 5:
                    _apply_status_style(cell, result.passed)
            row += 1

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(row - 1, 1)}"
    _auto_width(ws)


def _iter_check_rows(
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
) -> list[tuple[str, str, str, str, str, str, str, str, str]]:
    """Return rows for Checks Detail sheet."""
    rows: list[tuple[str, str, str, str, str, str, str, str, str]] = []
    if view_mode == "e2e" and e2e_results:
        sources: list[CaseEvaluationResult] = []
        for e2e in e2e_results:
            for stage in e2e.stages:
                stage = stage.model_copy(
                    update={
                        "test_case_id": f"{e2e.test_case_id} / {stage.eval_name}",
                        "run_id": e2e.run_id or stage.run_id,
                    }
                )
                sources.append(stage)
    else:
        sources = stage_results

    for result in sources:
        for check in result.deterministic_results:
            rows.append(
                (
                    result.test_case_id,
                    result.agent_name,
                    result.eval_name,
                    result.run_id,
                    "deterministic",
                    check.name,
                    _status_label(check.passed),
                    "",
                    "",
                    _truncate(check.reason, _REASON_TRUNCATE),
                )
            )
        for metric in result.metric_results:
            rows.append(
                (
                    result.test_case_id,
                    result.agent_name,
                    result.eval_name,
                    result.run_id,
                    "judge",
                    metric.name,
                    _status_label(metric.passed),
                    f"{metric.score:.2f}",
                    f"{metric.threshold:.2f}",
                    _truncate(metric.reason, _REASON_TRUNCATE),
                )
            )
    return rows


def _write_checks_detail_sheet(
    ws: Worksheet,
    *,
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
) -> None:
    ws.title = "Checks Detail"
    headers = [
        "Test Case ID",
        "Agent",
        "Suite / Stage",
        "Run ID",
        "Check Type",
        "Check Name",
        "Status",
        "Score",
        "Threshold",
        "Reason",
    ]
    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    _style_header_row(ws)

    row = 2
    for values in _iter_check_rows(stage_results, e2e_results, view_mode):
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=col == 10)
            if col == 7:
                _apply_status_style(cell, value == "PASS")
        row += 1

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(row - 1, 1)}"
    _auto_width(ws)


def _write_failed_cases_sheet(
    ws: Worksheet,
    *,
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
) -> None:
    ws.title = "Failed Cases"
    headers = [
        "Test Case ID",
        "Agent",
        "Suite / Stage",
        "Run ID",
        "Question",
        "Answer",
        "Expected / Golden",
        "Failure Reason",
    ]
    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    _style_header_row(ws)

    row = 2
    if view_mode == "e2e" and e2e_results:
        failed = [r for r in e2e_results if not r.passed]
        for e2e in sorted(failed, key=lambda r: (r.agent_name, r.test_case_id)):
            failed_stage = next((s for s in e2e.stages if not s.passed), e2e.stages[0] if e2e.stages else None)
            reason = _failure_reason(failed_stage) if failed_stage else ""
            values = [
                e2e.test_case_id,
                e2e.agent_name,
                f"e2e ({len(e2e.stages)} stages)",
                e2e.run_id,
                e2e.question,
                _truncate(_answer_from_e2e(e2e), _ANSWER_TRUNCATE * 2),
                _truncate(_expected_from_e2e(e2e), _ANSWER_TRUNCATE),
                reason,
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN_BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=col >= 5)
            row += 1
    else:
        failed = [r for r in stage_results if not r.passed]
        for result in sorted(failed, key=lambda r: (r.agent_name, r.test_case_id, r.eval_name)):
            values = [
                result.test_case_id,
                result.agent_name,
                result.eval_name,
                result.run_id,
                result.question,
                _truncate(result.answer, _ANSWER_TRUNCATE * 2),
                _truncate(result.expected_output, _ANSWER_TRUNCATE),
                _failure_reason(result),
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN_BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=col >= 5)
            row += 1

    if row == 2:
        ws.cell(row=2, column=1, value="No failed cases in this export scope.")

    ws.freeze_panes = "A2"
    _auto_width(ws, max_width=64)


def _write_metadata_sheet(
    ws: Worksheet,
    *,
    stage_results: list[CaseEvaluationResult],
    e2e_results: list[E2ECaseResult],
    view_mode: str,
) -> None:
    ws.title = "Case Metadata"
    headers = ["Test Case ID", "Agent", "Suite / Stage", "Run ID", "Field", "Value"]
    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    _style_header_row(ws)

    row = 2
    sources: list[CaseEvaluationResult] = []
    if view_mode == "e2e" and e2e_results:
        for e2e in e2e_results:
            for stage in e2e.stages:
                sources.append(
                    stage.model_copy(
                        update={
                            "test_case_id": e2e.test_case_id,
                            "run_id": e2e.run_id or stage.run_id,
                        }
                    )
                )
    else:
        sources = stage_results

    for result in sources:
        if not result.result_fields:
            continue
        for field, value in sorted(result.result_fields.items()):
            ws.cell(row=row, column=1, value=result.test_case_id).border = _THIN_BORDER
            ws.cell(row=row, column=2, value=result.agent_name).border = _THIN_BORDER
            ws.cell(row=row, column=3, value=result.eval_name).border = _THIN_BORDER
            ws.cell(row=row, column=4, value=result.run_id).border = _THIN_BORDER
            ws.cell(row=row, column=5, value=field).border = _THIN_BORDER
            cell = ws.cell(row=row, column=6, value=_truncate(str(value), 500))
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            row += 1

    if row == 2:
        ws.cell(row=2, column=1, value="No result_fields recorded for this export scope.")

    ws.freeze_panes = "A2"
    _auto_width(ws, max_width=64)


def export_evaluation_report(
    *,
    stage_results: list[CaseEvaluationResult] | None = None,
    e2e_results: list[E2ECaseResult] | None = None,
    view_mode: str = "stage",
    scope_label: str = "Single run",
    run_id: str = "",
) -> bytes:
    """
    Build a formatted .xlsx workbook for PO review.

    view_mode: "stage" (one row per suite×case) or "e2e" (one row per case).
    """
    stage_results = stage_results or []
    e2e_results = e2e_results or []
    if view_mode not in {"stage", "e2e"}:
        raise ValueError(f"view_mode must be 'stage' or 'e2e', got {view_mode!r}")

    wb = Workbook()
    default_ws = wb.active
    wb.remove(default_ws)

    _write_executive_summary(
        wb.create_sheet(),
        stage_results=stage_results,
        e2e_results=e2e_results,
        view_mode=view_mode,
        scope_label=scope_label,
        run_id=run_id,
    )
    _write_test_results_sheet(
        wb.create_sheet(),
        stage_results=stage_results,
        e2e_results=e2e_results,
        view_mode=view_mode,
    )
    _write_checks_detail_sheet(
        wb.create_sheet(),
        stage_results=stage_results,
        e2e_results=e2e_results,
        view_mode=view_mode,
    )
    _write_failed_cases_sheet(
        wb.create_sheet(),
        stage_results=stage_results,
        e2e_results=e2e_results,
        view_mode=view_mode,
    )
    _write_metadata_sheet(
        wb.create_sheet(),
        stage_results=stage_results,
        e2e_results=e2e_results,
        view_mode=view_mode,
    )

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export_filename(*, run_id: str = "", view_mode: str = "stage") -> str:
    """Suggested download filename for the dashboard."""
    stamp = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"eval_report_{view_mode}_{stamp}.xlsx"
