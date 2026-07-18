"""
CLI entry point: load test cases, invoke each one's agent (or replay a
captured trace), score with metrics, write results.

    python -m src.main --tests testdata/knowledge_agent/sanity --output outputs

Exit code 0 if every test case passed, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path

from src.core.logging_config import setup_logging
from src.reporting.dashboard import print_dashboard
from src.runners.evaluation_runner import EvaluationRunner
from src.runners.factories import AgentFactory, MetricFactory


def _collect_test_case_paths(tests_arg: str) -> list[str]:
    path = Path(tests_arg)
    if path.is_dir():
        return sorted(str(p) for p in path.glob("*.json"))
    return [tests_arg]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run agent evaluations")
    parser.add_argument("--tests", required=True, help="Test case JSON file or a directory of them")
    parser.add_argument("--configs", default="configs", help="Root config dir (must contain agents.yaml, cortex.yaml)")
    parser.add_argument("--output", default="outputs")
    args = parser.parse_args()

    setup_logging()

    agent_factory = AgentFactory(f"{args.configs}/agents.yaml")
    metric_factory = MetricFactory(f"{args.configs}/cortex.yaml")
    runner = EvaluationRunner(agent_factory, metric_factory)

    test_case_paths = _collect_test_case_paths(args.tests)
    if not test_case_paths:
        print(f"No test cases found at {args.tests}")
        return 1

    results = runner.run_all(test_case_paths, args.output)
    print_dashboard(results)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
