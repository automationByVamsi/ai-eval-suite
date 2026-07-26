"""
Generate golden test cases from source documents using DeepEval's
Synthesizer, driven by CORTEX (never OpenAI). Writes ready-to-run test-case
JSON files under testdata/<agent>/golden/.

    python -m src.synth --agent knowledge_agent

NOTE: DeepEval's Synthesizer API has changed across versions - if this
errors on `generate_goldens_from_docs(...)`, check `deepeval.synthesizer`
in your installed version and adjust the one call below; nothing else in
this file should need to change.
"""

import argparse
import json
from pathlib import Path

from deepeval.synthesizer import Synthesizer

from src.clients.cortex_client import CortexClient
from src.clients.cortex_deepeval import CortexDeepEvalLLM
from src.core.config import load_cortex_config, load_yaml
from src.core.logging_config import setup_logging


def _source_doc_paths(agent: str) -> list[str]:
    """
    Source docs are stored as {"title", "content"} JSON (see data/<agent>/source_docs/),
    but DeepEval's Synthesizer reads real text/pdf/docx files. Materialize each
    one as a plain .txt file in a cache subfolder and hand those paths over.
    """
    source_dir = Path("data") / agent / "source_docs"
    cache_dir = source_dir / "_generated_txt"
    cache_dir.mkdir(exist_ok=True)

    paths = []
    for json_path in sorted(source_dir.glob("*.json")):
        doc = json.loads(json_path.read_text())
        txt_path = cache_dir / f"{json_path.stem}.txt"
        txt_path.write_text(doc.get("content", ""))
        paths.append(str(txt_path))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate golden test cases from source docs via DeepEval + CORTEX")
    parser.add_argument("--agent", required=True, help="Agent profile name, e.g. knowledge_agent")
    parser.add_argument("--configs", default="configs")
    parser.add_argument("--output-tag", default="golden")
    args = parser.parse_args()

    setup_logging()

    synth_config = load_yaml(Path(args.configs) / "synthesizer" / args.agent / "config.yaml")
    cortex_client = CortexClient(load_cortex_config(f"{args.configs}/cortex.yaml"))
    cortex_llm = CortexDeepEvalLLM(cortex_client)

    doc_paths = _source_doc_paths(args.agent)
    if not doc_paths:
        raise SystemExit(f"No source docs found under data/{args.agent}/source_docs/")

    synthesizer = Synthesizer(model=cortex_llm)
    synthesizer.generate_goldens_from_docs(
        document_paths=doc_paths,
        max_goldens_per_document=synth_config.get("max_goldens_per_document", 2),
    )

    out_dir = Path("testdata") / args.agent / args.output_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, golden in enumerate(synthesizer.synthetic_goldens, start=1):
        test_case_id = f"TC_GOLDEN_{i:03d}"
        test_case = {
            "test_case_id": test_case_id,
            "description": "Auto-generated golden test case",
            "agent_name": synth_config.get("agent_name", f"{args.agent}_synth"),
            "input": {"question": golden.input},
            "expected": {"answer": golden.expected_output or ""},
            "metrics": [],
        }
        out_path = out_dir / f"{test_case_id}.json"
        out_path.write_text(json.dumps(test_case, indent=2))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
