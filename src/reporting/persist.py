# Writes evaluation results for scripts/dashboard_app.py.
#
# Layout (timestamped runs so make dashboard always opens the latest):
#
#     outputs/dashboard/
#       LATEST                          # relative path, e.g. runs/20260720_175812
#       runs/
#         20260720_175812/
#           <agent>/<eval>__<id>.json
#           <agent>/e2e__<id>.json
#
# One pytest process = one run directory (shared across stage / e2e publishes).
# Override with DASHBOARD_RUN_DIR (absolute path) or DASHBOARD_RUN_ID (stamp name).
#
# Common all-agents view: Streamlit sidebar → Scope → "All runs (all agents)".
# To force KA + FF into the *same* single-run folder without changing code:
#   DASHBOARD_RUN_ID=demo_all make test-ka-sanity-judges
#   DASHBOARD_RUN_ID=demo_all make test-ff-sanity-judges


from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from src.models.agent_response import AgentResponse
from src.models.evaluation_result import (
    CaseEvaluationResult,
    DeterministicCheckResult,
    E2ECaseResult,
)
from src.models.metric_result import MetricResult

_lock = Lock()
_current_run_dir: Path | None = None

DEFAULT_DASHBOARD_ROOT = "outputs/dashboard"


def ensure_run_dir(root: str | Path = DEFAULT_DASHBOARD_ROOT) -> Path:
    """
    Create (once per process) a timestamped run dir and update LATEST.
    All publishes in this process write into the same run.
    """
    global _current_run_dir
    with _lock:
        if _current_run_dir is not None:
            return _current_run_dir

        root_p = Path(root)
        root_p.mkdir(parents=True, exist_ok=True)

        override = os.environ.get("DASHBOARD_RUN_DIR")
        if override:
            run_dir = Path(override)
        else:
            stamp = os.environ.get("DASHBOARD_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = root_p / "runs" / stamp

        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            pointer = str(run_dir.resolve().relative_to(root_p.resolve()))
        except ValueError:
            pointer = str(run_dir.resolve())
        (root_p / "LATEST").write_text(pointer + "\n")

        _current_run_dir = run_dir
        return run_dir


def reset_run_dir() -> None:
    """Clear process run dir (tests only)."""
    global _current_run_dir
    with _lock:
        _current_run_dir = None


def list_runs(root: str | Path = DEFAULT_DASHBOARD_ROOT) -> list[Path]:
    """Newest-first timestamped run directories."""
    runs_dir = Path(root) / "runs"
    if not runs_dir.is_dir():
        return []
    return sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )


def resolve_latest_run(root: str | Path = DEFAULT_DASHBOARD_ROOT) -> Path | None:
    """Resolve LATEST pointer, else newest runs/*, else legacy flat root if it has JSON."""
    root_p = Path(root)
    latest_file = root_p / "LATEST"
    if latest_file.is_file():
        pointer = latest_file.read_text().strip()
        if pointer:
            cand = Path(pointer) if Path(pointer).is_absolute() else root_p / pointer
            if cand.is_dir():
                return cand

    runs = list_runs(root_p)
    if runs:
        return runs[0]

    # Pre-timestamp layout: agent folders directly under root
    if any(p.suffix == ".json" for p in root_p.rglob("*.json") if "runs" not in p.parts):
        return root_p
    return None


def save_eval_result(result: CaseEvaluationResult, output_dir: str) -> Path:
    agent_dir = Path(output_dir) / (result.agent_name or "unknown_agent")
    agent_dir.mkdir(parents=True, exist_ok=True)
    out_path = agent_dir / f"{result.eval_name}__{result.test_case_id}.json"
    out_path.write_text(result.model_dump_json(indent=2))
    return out_path


def save_e2e_result(result: E2ECaseResult, output_dir: str) -> Path:
    agent_dir = Path(output_dir) / (result.agent_name or "unknown_agent")
    agent_dir.mkdir(parents=True, exist_ok=True)
    out_path = agent_dir / f"e2e__{result.test_case_id}.json"
    out_path.write_text(result.model_dump_json(indent=2))
    return out_path


def _question_from_case(case: dict[str, Any]) -> str:
    inp = case.get("input") or {}
    if not isinstance(inp, dict):
        return ""
    for key in ("question", "complaint_ref"):
        if inp.get(key):
            return str(inp[key])
    for value in inp.values():
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _expected_output(case: dict[str, Any], response: AgentResponse) -> str:
    """SME golden text when present (KA); FF relies on response.context chunks."""
    meta = response.metadata or {}
    if meta.get("expected_answer"):
        return str(meta["expected_answer"])
    expected = case.get("expected") or {}
    if not isinstance(expected, dict):
        return ""
    return str(expected.get("expected_answer") or expected.get("answer") or "")


def publish_suite_result(
    *,
    agent_name: str,
    suite: str,
    case: dict[str, Any],
    response: AgentResponse,
    judges: list[Any] | None = None,
    deterministic: list[Any] | None = None,
    result_fields: dict[str, Any] | None = None,
    dashboard_root: str | Path = DEFAULT_DASHBOARD_ROOT,
) -> Path:
    """
    Write one suite × case result for Streamlit (pass or fail).

    `judges` / `deterministic` items need .name/.passed/.reason;
    judges may also have .score/.threshold (CheckResult from evaluate() works).
    """
    judges = judges or []
    deterministic = deterministic or []

    metric_results = [
        MetricResult(
            name=j.name,
            score=float(j.score if getattr(j, "score", None) is not None else 0.0),
            threshold=float(j.threshold if getattr(j, "threshold", None) is not None else 0.0),
            passed=bool(j.passed),
            reason=str(getattr(j, "reason", "") or ""),
        )
        for j in judges
    ]
    det_results = [
        DeterministicCheckResult(
            name=str(c.name),
            passed=bool(c.passed),
            reason=str(getattr(c, "reason", "") or ""),
        )
        for c in deterministic
    ]
    result = CaseEvaluationResult(
        eval_name=suite,
        test_case_id=str(case.get("test_case_id") or "unknown"),
        agent_name=agent_name,
        question=_question_from_case(case),
        answer=response.answer or "",
        context=list(response.context or []),
        expected_output=_expected_output(case, response),
        latency_ms=response.latency_ms,
        deterministic_results=det_results,
        metric_results=metric_results,
        result_fields=dict(result_fields or {}),
    )
    run_dir = ensure_run_dir(dashboard_root)
    return save_eval_result(result, str(run_dir))


# Backward-compatible alias
save_stage_result = save_eval_result
