#!/usr/bin/env python3
"""
VERDICT CLI — multi-run reliability + baseline regression on existing cases.

Examples:
  # 1) Freeze a trusted baseline from current sanity traces (Layer-1 only)
  python -m scripts.run_verdict --save-baseline --n 5

  # 2) Show what a broken build looks like vs that baseline
  python -m scripts.run_verdict --simulate-regression --n 5

  # 3) Also re-sample CORTEX judges (slower, needs network)
  python -m scripts.run_verdict --judges --n 3 --save-baseline
"""

from __future__ import annotations

import argparse
import sys

from src.verdict.runner import run_verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VERDICT reliability checks")
    parser.add_argument("--n", type=int, default=5, help="Repetitions per case×stage (default 5)")
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Case ids (default: all under testdata/knowledge_agent/sanity)",
    )
    parser.add_argument(
        "--stages",
        nargs="*",
        default=None,
        help="Stages (default: stage1_query_rewrite stage2_anchor_node)",
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
        help="Inject DAFAT-style stage drops on most reps (demo usefulness)",
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
        n_reps=args.n,
        case_ids=args.cases,
        stages=args.stages,
        run_judges=args.judges,
        simulate_regression=args.simulate_regression,
        save_as_baseline=args.save_baseline,
        compare_baseline=not args.no_compare,
        baseline_name=args.baseline_name,
        drop_threshold=args.drop_threshold,
        output_dir=args.output,
    )

    if report.has_regression:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
