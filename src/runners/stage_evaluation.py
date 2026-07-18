"""
Shared evaluate-loop: run a stage evaluator over a list of trace files,
print each summary, and persist each result for the dashboard.
"""

from pathlib import Path

from src.evaluators.base_stage_evaluator import BaseStageEvaluator
from src.models.evaluation_result import StageEvaluationResult
from src.reporting.persist import save_stage_result


def evaluate_traces(
    evaluator: BaseStageEvaluator, trace_files: list[Path], output_dir: str
) -> list[StageEvaluationResult]:
    results = [evaluator.evaluate(str(p)) for p in trace_files]
    for r in results:
        r.print_summary()
        save_stage_result(r, output_dir)
    return results
