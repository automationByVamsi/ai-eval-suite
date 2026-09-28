#!/usr/bin/env python3
"""
A/B comparative evaluation CLI.

  python -m scripts.run_comparison --config configs/comparisons/demo_offline.yaml

Does not replace python -m src.main or VERDICT commands.
"""

from __future__ import annotations

import argparse
import sys

from src.comparison.config import load_comparison_spec
from src.comparison.runner import run_comparison
from src.core.logging_config import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run paired Candidate A vs Candidate B comparative evaluation"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to configs/comparisons/*.yaml",
    )
    parser.add_argument(
        "--configs",
        default="configs",
        help="Root config dir for agents.yaml / cortex.yaml (live mode)",
    )
    parser.add_argument(
        "--stability",
        action="store_true",
        help="Force A/A and B/B stability checks (also auto when repetitions>=2)",
    )
    parser.add_argument(
        "--no-stability",
        action="store_true",
        help="Disable A/A and B/B stability checks",
    )
    args = parser.parse_args()

    setup_logging()
    spec = load_comparison_spec(
        args.config,
        agents_path=f"{args.configs}/agents.yaml",
    )

    print("\nExperiment     ", spec.name)
    print("Candidate A    ", f"{spec.candidate_a.name} ({spec.candidate_a.agent})")
    print("Candidate B    ", f"{spec.candidate_b.name} ({spec.candidate_b.agent})")
    print("Dataset        ", f"{spec.dataset_agent}/{spec.dataset_suite}")
    print("Repetitions    ", spec.repetitions)
    print("Mode           ", spec.mode)
    print("Dimension      ", spec.dimension.value)

    if args.no_stability:
        run_stability = False
    elif args.stability:
        run_stability = True
    else:
        run_stability = bool(spec.require_stability)
    result = run_comparison(
        spec,
        run_stability=run_stability,
        agents_path=f"{args.configs}/agents.yaml",
        cortex_config=f"{args.configs}/cortex.yaml",
    )

    out = f"{spec.output_dir}/{spec.name}/comparison_result.json"
    print(f"Wrote {out}")

    if result.gate and not result.gate.comparison_acceptable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
