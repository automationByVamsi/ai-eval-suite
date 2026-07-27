"""
Knowledge Agent synthesizer CLI.

Modes (from configs/synthesizer/<agent>/config.yaml):
  generate  — Athena page → clean HTML → DeepEval goldens → testdata/
  run       — load goldens → live ADK → optional judges / dashboard

Examples:
  python -m src.synth --agent knowledge_agent --mode generate
  python -m src.synth --agent knowledge_agent --mode generate --fixture
  python -m src.synth --agent knowledge_agent --mode run
"""

from __future__ import annotations

import argparse

from src.core.logging_config import setup_logging
from src.synthesizer.pipeline import generate_goldens, run_goldens


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or run Knowledge Agent synthesizer goldens"
    )
    parser.add_argument("--agent", default="knowledge_agent")
    parser.add_argument(
        "--mode",
        choices=("generate", "run"),
        required=True,
        help="generate = Athena→goldens; run = ADK invoke (+ judges)",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="generate mode only: read fetch.fixture_path instead of live Athena",
    )
    parser.add_argument("--configs", default="configs")
    args = parser.parse_args()

    setup_logging()

    if args.mode == "generate":
        generate_goldens(
            args.agent,
            configs_dir=args.configs,
            use_fixture=True if args.fixture else None,
        )
    else:
        run_goldens(args.agent, configs_dir=args.configs)


if __name__ == "__main__":
    main()
