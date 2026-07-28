"""
Knowledge Agent synthesizer CLI (build goldens only — evals stay in pytest).

  # Athena → cleaned source docs (like Fact Find payload generation)
  python -m src.synth --agent knowledge_agent --prepare --page-id 8708
  python -m src.synth --agent knowledge_agent --prepare --page-id 8708 --fixture 8708-response.json

  # cleaned source docs → DeepEval goldens
  python -m src.synth --agent knowledge_agent --generate
"""

from __future__ import annotations

import argparse

from src.core.logging_config import setup_logging
from src.synthesizer.pipeline import KnowledgeAgentSynthesizer


def main() -> None:
    """Run the synthesizer CLI for Athena prep and golden generation."""
    parser = argparse.ArgumentParser(
        description="Prepare Athena source docs and/or generate KA goldens"
    )
    parser.add_argument("--agent", default="knowledge_agent")
    parser.add_argument("--configs", default="configs")

    parser.add_argument(
        "--prepare",
        action="store_true",
        help="fetch Athena → clean → save under source_docs_dir",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="read source_docs_dir → write goldens under output_dir",
    )
    parser.add_argument(
        "--page-id",
        action="append",
        dest="page_ids",
        default=[],
        help="Athena page id (repeatable). Required with --prepare.",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Optional local Athena JSON (offline prepare; skips live GET)",
    )
    args = parser.parse_args()

    if not args.prepare and not args.generate:
        parser.error("pass --prepare and/or --generate")

    setup_logging()
    synth = KnowledgeAgentSynthesizer(
        args.agent,
        configs_dir=args.configs,
        fixture_path=args.fixture,
    )

    if args.prepare:
        if not args.page_ids:
            parser.error("--prepare requires at least one --page-id")
        for page_id in args.page_ids:
            synth.prepare_page(page_id)

    if args.generate:
        synth.generate_goldens()


if __name__ == "__main__":
    main()
