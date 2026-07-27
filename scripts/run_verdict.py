#!/usr/bin/env python3
"""
VERDICT CLI — multi-run reliability + baseline regression (any registered agent).

Examples:
  python -m scripts.run_verdict --agent knowledge_agent --n 5 --save-baseline
  python -m scripts.run_verdict --agent fact_find_workflow --n 5
  python -m scripts.run_verdict --agent knowledge_agent --simulate-regression --n 5
"""

from __future__ import annotations

import argparse
import sys

from src.verdict.registry import list_agents, load_builtin_packs
from src.verdict.runner import run_verdict


def main() -> int:
    load_builtin_packs()
    agents = list_agents()

    parser = argparse.ArgumentParser(description="Run VERDICT reliability checks")
    parser.add_argument(
        "--agent",
        default="knowledge_agent",
        choices=agents or None,
        help=f"Agent to score (registered: {', '.join(agents) or '…'})",
    )
    parser.add_argument(
        "--suite",
        default=None,
        help="Testdata / traces suite (default: agent pack default, usually sanity)",
    )
    parser.add_argument("--n", type=int, default=5, help="Repetitions per case×pack (default 5)")
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Case ids (default: all cases in the suite)",
    )
    parser.add_argument(
        "--packs",
        "--stages",
        dest="packs",
        nargs="*",
        default=None,
        help="Check packs to run (default: all packs for the agent)",
    )
    parser.add_argument(
        "--judges",
        action="store_true",
        help="Also run Layer-2 CORTEX/GEval judges each rep (slower)",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Write current aggregates as the trusted baseline",
    )
    parser.add_argument(
        "--no-compare",
        action="store_true",
        help="Skip baseline diff even if a baseline exists",
    )
    parser.add_argument(
        "--simulate-regression",
        action="store_true",
        help="Inject intentional drops on most reps (demo usefulness)",
    )
    parser.add_argument("--baseline-name", default="latest")
    parser.add_argument(
        "--drop-threshold",
        type=float,
        default=0.15,
        help="Pass-rate drop (absolute) that counts as regression (default 0.15)",
    )
    parser.add_argument("--output", default="outputs/verdict")
    args = parser.parse_args()

    report = run_verdict(
        agent=args.agent,
        suite=args.suite,
        n_reps=args.n,
        case_ids=args.cases,
        packs=args.packs,
        run_judges=args.judges,
        simulate_regression=args.simulate_regression,
        save_as_baseline=args.save_baseline,
        compare_baseline=not args.no_compare,
        baseline_name=args.baseline_name,
        drop_threshold=args.drop_threshold,
        output_dir=args.output,
    )

    return 1 if report.has_regression else 0


if __name__ == "__main__":
    sys.exit(main())
