"""
Convenience wrapper for the knowledge_agent's stage 1 (query rewrite) -
same thing as run_stage.py but with --agent/--stage already filled in, for
the common case of "just run stage 1 against sanity traces".

    python -m scripts.run_stage1
    python -m scripts.run_stage1 --traces outputs/traces/knowledge_agent/regression
"""

import argparse
import sys
from pathlib import Path

from src.core.config import load_stage_config
from src.core.logging_config import setup_logging
from src.evaluators.knowledge_agent.stage1_query_rewrite import Stage1QueryRewriteEvaluator
from src.runners.factories import MetricFactory
from src.runners.stage_evaluation import evaluate_traces


def main() -> int:
    parser = argparse.ArgumentParser(description="Run knowledge_agent stage1 (query rewrite) against captured traces")
    parser.add_argument("--traces", default="outputs/traces/knowledge_agent/sanity")
    parser.add_argument("--configs", default="configs")
    parser.add_argument("--output", default="outputs/dashboard", help="Directory to write per-test-case JSON for the dashboard")
    args = parser.parse_args()

    setup_logging()

    stage_config = load_stage_config("knowledge_agent", "stage1_query_rewrite", base_dir=f"{args.configs}/evaluations")
    metric_factory = MetricFactory(f"{args.configs}/cortex.yaml")
    evaluator = Stage1QueryRewriteEvaluator(metric_factory, stage_config)

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
