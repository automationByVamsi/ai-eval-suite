"""
Generic single-stage runner: given an agent profile + stage name + a trace
file (or directory of them), run that stage's evaluator and print results.

    python -m scripts.run_stage --agent knowledge_agent --stage stage1_query_rewrite \\
        --traces outputs/traces/knowledge_agent/sanity

To add a new stage: subclass BaseStageEvaluator, add a config yaml, and add
one line to STAGE_EVALUATORS in src/runners/stage_registry.py - nothing in
this file changes.
"""

import argparse
import sys
from pathlib import Path

from src.core.config import load_stage_config
from src.core.logging_config import setup_logging
from src.runners.factories import MetricFactory
from src.runners.stage_evaluation import evaluate_traces
from src.runners.stage_registry import load_evaluator_class


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single stage evaluator against captured traces")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--traces", required=True, help="Trace JSON file or a directory of them")
    parser.add_argument("--configs", default="configs")
    parser.add_argument("--output", default="outputs/dashboard", help="Directory to write per-test-case JSON for the dashboard")
    args = parser.parse_args()

    setup_logging()

    evaluator_cls = load_evaluator_class(args.agent, args.stage)
    stage_config = load_stage_config(args.agent, args.stage, base_dir=f"{args.configs}/evaluations")
    metric_factory = MetricFactory(f"{args.configs}/cortex.yaml")
    evaluator = evaluator_cls(metric_factory, stage_config)

    trace_path = Path(args.traces)
    trace_files = sorted(trace_path.glob("*.json")) if trace_path.is_dir() else [trace_path]
    if not trace_files:
        raise SystemExit(f"No trace files found at {args.traces}")

    results = evaluate_traces(evaluator, trace_files, args.output)

    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} stage checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
