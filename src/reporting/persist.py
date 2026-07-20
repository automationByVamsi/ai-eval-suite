"""
Writes evaluation results for scripts/dashboard_app.py.

Layout (timestamped runs so make dashboard always opens the latest):

    outputs/dashboard/
      LATEST                          # relative path, e.g. runs/20260720_175812
      runs/
        20260720_175812/
          <agent>/<eval>__<id>.json
          <agent>/e2e__<id>.json

One pytest process = one run directory (shared across stage / e2e publishes).
Override with DASHBOARD_RUN_DIR (absolute path) or DASHBOARD_RUN_ID (stamp name).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock

from src.models.evaluation_result import CaseEvaluationResult, E2ECaseResult

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


# Backward-compatible alias
save_stage_result = save_eval_result
