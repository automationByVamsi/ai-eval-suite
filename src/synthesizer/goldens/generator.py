"""
Generate golden test cases from cleaned source docs (DeepEval synthesizer).

Loops styles from synth YAML: each style file → its own StylingConfig batch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepeval.synthesizer import Synthesizer

from src.clients.cortex_client import CortexClient
from src.clients.cortex_deepeval import CortexDeepEvalLLM
from src.core.config import load_cortex_config
from src.synthesizer.goldens.evolution import build_evolution_config
from src.synthesizer.goldens.filtration import build_filtration_config
from src.synthesizer.goldens.styling import build_styling_config


def load_cleaned_docs(docs_dir: Path) -> list[dict[str, Any]]:
    """Load cleaned source-doc JSON files that have usable content."""
    docs: list[dict[str, Any]] = []
    for path in sorted(docs_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("content"):
            continue
        docs.append(
            {
                "page_id": str(data.get("page_id") or path.stem),
                "title": str(data.get("title") or ""),
                "content": str(data["content"]),
            }
        )
    return docs


def _resolve(agent_dir: Path, name: str) -> Path:
    """Resolve a config-relative path, falling back to the agent directory."""
    path = Path(name)
    if path.is_file():
        return path
    cand = agent_dir / name
    if cand.is_file():
        return cand
    return agent_dir / path.name


def generate_goldens_from_docs(
    *,
    agent: str,
    agent_dir: Path,
    cfg: dict[str, Any],
    configs_dir: Path,
    cleaned_docs_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """
    For each entry in cfg['styles'], build StylingConfig and synthesize goldens.
    """
    docs = load_cleaned_docs(cleaned_docs_dir)
    if not docs:
        raise RuntimeError(
            f"No cleaned docs in {cleaned_docs_dir}/ — run --prepare --page-id … first"
        )

    styles = cfg.get("styles") or []
    if not styles:
        raise RuntimeError(
            f"{agent_dir}/config.yaml must define a non-empty 'styles:' list"
        )

    instructions_path = _resolve(
        agent_dir, str(cfg.get("instruction_file") or "instructions.md")
    )
    shared_instructions = (
        instructions_path.read_text(encoding="utf-8")
        if instructions_path.is_file()
        else ""
    )

    evo_name = cfg.get("evolution_file")
    evolution = build_evolution_config(
        _resolve(agent_dir, str(evo_name)) if evo_name else None
    )

    cortex = CortexClient(load_cortex_config(str(configs_dir / "cortex.yaml")))
    llm = CortexDeepEvalLLM(cortex)

    filt_name = cfg.get("filtration_file")
    filtration = build_filtration_config(
        _resolve(agent_dir, str(filt_name)) if filt_name else None,
        critic_model=llm,
    )

    include_expected = bool(cfg.get("include_expected_output", True))
    default_max = int(cfg.get("max_goldens_per_context", 2))
    agent_name = str(cfg.get("agent_name") or agent)

    contexts = [[d["content"]] for d in docs]
    page_ids = [d["page_id"] for d in docs]

    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("TC_GOLDEN_*.json"):
        old.unlink()

    written: list[Path] = []
    global_i = 0

    for style in styles:
        if not isinstance(style, dict) or not style.get("name") or not style.get("file"):
            raise ValueError(
                f"Each styles entry needs name + file, got: {style!r}"
            )
        style_name = str(style["name"])
        style_path = _resolve(agent_dir, str(style["file"]))
        if not style_path.is_file():
            raise FileNotFoundError(f"Style file not found: {style_path}")

        max_goldens = int(style.get("max_goldens_per_context", default_max))
        styling = build_styling_config(
            style_path, shared_instructions=shared_instructions
        )

        synthesizer = Synthesizer(
            model=llm,
            async_mode=False,
            styling_config=styling,
            evolution_config=evolution,
            filtration_config=filtration,
        )
        goldens = synthesizer.generate_goldens_from_contexts(
            contexts=contexts,
            include_expected_output=include_expected,
            max_goldens_per_context=max_goldens,
        )

        for golden in goldens:
            global_i += 1
            page_id = page_ids[(global_i - 1) % len(page_ids)]
            test_case_id = f"TC_GOLDEN_{style_name}_{global_i:03d}"
            case = {
                "test_case_id": test_case_id,
                "description": (
                    f"Synthesized ({style_name}) from Athena page {page_id}"
                ),
                "agent_name": agent_name,
                "input": {"question": golden.input},
                "expected": {
                    "answer": golden.expected_output or "",
                    "source_page_id": page_id,
                    "style": style_name,
                },
            }
            path = output_dir / f"{test_case_id}.json"
            path.write_text(json.dumps(case, indent=2), encoding="utf-8")
            written.append(path)
            print(f"Wrote {path}")

        print(f"Style {style_name!r}: {len(goldens)} golden(s)")

    print(f"Generated {len(written)} golden(s) under {output_dir}/")
    return written
