"""
Writes one StageEvaluationResult per test case to disk, so
scripts/dashboard_app.py can render results without re-running anything.
"""

from pathlib import Path

from src.models.evaluation_result import StageEvaluationResult


def save_stage_result(result: StageEvaluationResult, output_dir: str) -> Path:
    agent_dir = Path(output_dir) / (result.agent_name or "unknown_agent")
    agent_dir.mkdir(parents=True, exist_ok=True)
    out_path = agent_dir / f"{result.stage_name}__{result.test_case_id}.json"
    out_path.write_text(result.model_dump_json(indent=2))
    return out_path
