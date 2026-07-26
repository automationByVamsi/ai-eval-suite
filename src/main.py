"""
CLI entry point: load test cases, live ADK invoke, score with metrics, write results.

    python -m src.main --tests testdata/knowledge_agent/sanity --output outputs

Exit code 0 if every test case passed, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path

from src.core.logging_config import setup_logging
from src.reporting.dashboard import print_dashboard
from src.runners.evaluation_runner import EvaluationRunner
from src.runners.factories import MetricFactory


def _collect_test_case_paths(tests_arg: str) -> list[str]:
    path = Path(tests_arg)
    if path.is_dir():
        return sorted(str(p) for p in path.glob("*.json"))
    return [tests_arg]


def _infer_save_dir(tests_arg: str) -> Path | None:
    """testdata/<profile>/<tag> → outputs/traces/<profile>/<tag>."""
    path = Path(tests_arg)
    if path.is_file():
        path = path.parent
    parts = path.parts
    if "testdata" in parts:
        i = parts.index("testdata")
        rest = parts[i + 1 :]
        if len(rest) >= 2:
            return Path("outputs/traces") / rest[0] / rest[1]
        if len(rest) == 1:
            return Path("outputs/traces") / rest[0] / "sanity"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run agent evaluations (live ADK)")
    parser.add_argument("--tests", required=True, help="Test case JSON file or a directory of them")
    parser.add_argument("--configs", default="configs", help="Root config dir (agents.yaml, cortex.yaml)")
    parser.add_argument("--output", default="outputs")
    parser.add_argument(
        "--save-dir",
        default=None,
        help="Where to save ADK JSON (default: inferred from --tests under outputs/traces/)",
    )
    args = parser.parse_args()

    setup_logging()

    metric_factory = MetricFactory(f"{args.configs}/cortex.yaml")
    save_dir = Path(args.save_dir) if args.save_dir else _infer_save_dir(args.tests)
    runner = EvaluationRunner(
        metric_factory,
        agents_path=f"{args.configs}/agents.yaml",
        save_dir=save_dir,
    )

    test_case_paths = _collect_test_case_paths(args.tests)
    if not test_case_paths:
        print(f"No test cases found at {args.tests}")
        return 1

    results = runner.run_all(test_case_paths, args.output)
    print_dashboard(results)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
