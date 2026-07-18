"""
Single day-to-day entrypoint: make sure traces exist (per --mode), then
evaluate them. Wraps the same building blocks capture_traces.py / run_stage.py
use, so all three stay consistent.

  --mode cache        never call the agent - reuse traces only, hard-fail if
                       any test case has no captured trace
  --mode incremental   call the agent only for test cases missing a trace
  --mode refresh       call the agent for every test case, overwrite traces

    python -m scripts.run_tests --agent knowledge_agent --tag sanity \\
        --stage stage1_query_rewrite --mode cache
"""

import argparse
import sys

from src.core.logging_config import setup_logging
from src.runners.test_run import run_tests


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure traces exist per --mode, then evaluate them")
    parser.add_argument("--agent", required=True, help="Folder name under testdata/ and key in STAGE_EVALUATORS, e.g. knowledge_agent")
    parser.add_argument("--tag", required=True, help="Test-data tier folder under testdata/<agent>/, e.g. sanity, golden, bronze, silver, regression")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--mode", required=True, choices=["cache", "incremental", "refresh"])
    parser.add_argument("--configs", default="configs")
    parser.add_argument("--output", default="outputs/dashboard", help="Directory to write per-test-case JSON for the dashboard")
    args = parser.parse_args()

    setup_logging()

    try:
        results = run_tests(args.agent, args.tag, args.stage, args.mode, args.configs, args.output)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} stage checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
