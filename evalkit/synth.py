"""
Synthesizer: generate test cases ("goldens") from source documents.

Everything lives in the agent's synth/ folder:

    agents/<agent>/synth/
      synth.yaml          styles, how many per document, question variety, quality filter
      instructions.md     rules every generated question/answer must follow
      styles/*.md         one file per question style (## scenario / ## task / ## input_format /
                          ## expected_output_format)
      sources/*.txt       the documents to generate from — one file each, the file name is its id
      sources.py          optional: fetch documents from a system (e.g. Athena) into sources/

Two commands:
    make sources AGENT=knowledge_agent IDS="8708 9001"   calls sources.py fetch(id) for each id
    make goldens AGENT=knowledge_agent                   sources/*.txt -> testdata/golden/*.json

Generated cases are normal test cases: review them, then `make run AGENT=.. SUITE=golden`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from evalkit.config import ConfigError, load_agent


def fetch_sources(agent_name: str, source_ids: list[str]) -> list[Path]:
    """Run the agent's synth/sources.py fetch(id) -> (title, text) and save sources/<id>.txt."""
    synth_dir = load_agent(agent_name).folder / "synth"
    module_path = synth_dir / "sources.py"
    if not module_path.is_file():
        raise ConfigError(f"{module_path} not found — put .txt files in {synth_dir / 'sources'} instead")
    spec = importlib.util.spec_from_file_location(f"{agent_name}_sources", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    written = []
    for source_id in source_ids:
        title, text = module.fetch(source_id)
        if not text.strip():
            raise ValueError(f"Source {source_id} has no text after cleaning")
        path = synth_dir / "sources" / f"{source_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{title}\n\n{text}".strip() + "\n")
        print(f"Saved {path} ({len(text)} characters)")
        written.append(path)
    return written


def generate_goldens(agent_name: str, *, replace: bool = False) -> list[Path]:
    """Generate test cases from synth/sources/*.txt with DeepEval's Synthesizer (judge model = CORTEX)."""
    from deepeval.synthesizer import Synthesizer
    from deepeval.synthesizer.config import EvolutionConfig, FiltrationConfig, StylingConfig
    from deepeval.synthesizer.types import Evolution

    from evalkit.cortex import deepeval_llm

    agent = load_agent(agent_name)
    synth_dir = agent.folder / "synth"
    settings = _load_settings(synth_dir)

    sources = {p.stem: p.read_text().strip() for p in sorted((synth_dir / "sources").glob("*.txt"))}
    sources = {k: v for k, v in sources.items() if v}
    if not sources:
        raise ConfigError(f"No documents in {synth_dir / 'sources'} — run `make sources` or add .txt files")

    output = agent.folder / "testdata" / settings.get("output_suite", "golden")
    existing = list(output.glob("*.json"))
    if existing and not replace:
        raise ConfigError(f"{output} already has {len(existing)} case(s). Review/move them, "
                          f"or regenerate with REPLACE=1 (deletes them).")

    llm = deepeval_llm()
    instructions = (synth_dir / settings["instructions"]).read_text().strip() if settings.get("instructions") else ""
    evolution = dict(settings.get("evolutions") or {})
    rounds = int(evolution.pop("rounds", 1))
    evolution_config = (EvolutionConfig(num_evolutions=rounds,
                                        evolutions={Evolution[k]: float(v) for k, v in evolution.items()})
                        if evolution else EvolutionConfig(num_evolutions=rounds))   # DeepEval's default mix
    quality = settings.get("quality_filter") or {}
    filtration_config = FiltrationConfig(
        synthetic_input_quality_threshold=float(quality.get("min_quality", 0.5)),
        max_quality_retries=int(quality.get("retries", 3)),
        critic_model=llm,                       # without this DeepEval would call OpenAI
    )

    cases: list[dict[str, Any]] = []
    for style_name, style in settings["styles"].items():
        sections = _style_sections(synth_dir / style["file"])
        scenario = "\n\n".join(s for s in [sections.get("scenario", ""), instructions] if s)
        synthesizer = Synthesizer(
            model=llm,
            async_mode=False,
            styling_config=StylingConfig(
                scenario=scenario or None,
                task=sections.get("task") or None,
                input_format=sections.get("input_format") or None,
                expected_output_format=sections.get("expected_output_format") or None,
            ),
            evolution_config=evolution_config,
            filtration_config=filtration_config,
        )
        goldens = synthesizer.generate_goldens_from_contexts(
            contexts=[[text] for text in sources.values()],
            source_files=list(sources),
            include_expected_output=bool(settings.get("include_expected_answer", True)),
            max_goldens_per_context=int(style.get("per_source", 2)),
        )
        for number, golden in enumerate(goldens, start=1):
            source = golden.source_file or next(
                (doc_id for doc_id, text in sources.items() if text in (golden.context or [])), "")
            cases.append({
                "test_case_id": f"GOLDEN_{style_name}_{number:03d}",
                "description": f"Generated ({style_name}) from source {source} on {date.today()}",
                "input": {agent.input_field: golden.input},
                "expected": {
                    "expected_answer": golden.expected_output or "",
                    "source": source,
                    "style": style_name,
                },
            })
        print(f"Style {style_name}: {len(goldens)} case(s)")

    # Only touch the folder once generation has succeeded.
    for path in existing:
        path.unlink()
    output.mkdir(parents=True, exist_ok=True)
    written = []
    for case in cases:
        path = output / f"{case['test_case_id']}.json"
        path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
        written.append(path)

    print(f"Wrote {len(written)} case(s) to {output}. Review them, then: "
          f"make run AGENT={agent_name} SUITE={output.name}")
    return written


def _load_settings(synth_dir: Path) -> dict[str, Any]:
    path = synth_dir / "synth.yaml"
    if not path.is_file():
        raise ConfigError(f"{path} not found — see agents/knowledge_agent/synth/ for an example")
    settings = yaml.safe_load(path.read_text()) or {}
    allowed = {"output_suite", "include_expected_answer", "instructions", "styles", "evolutions", "quality_filter"}
    if set(settings) - allowed:
        raise ConfigError(f"{path}: unknown keys {sorted(set(settings) - allowed)}")
    if not settings.get("styles"):
        raise ConfigError(f"{path}: add at least one entry under styles:")
    for name, style in settings["styles"].items():
        if not (synth_dir / style.get("file", "")).is_file():
            raise ConfigError(f"{path}: style '{name}' file not found: {style.get('file')}")
    from deepeval.synthesizer.types import Evolution
    unknown = [k for k in (settings.get("evolutions") or {}) if k != "rounds" and k not in Evolution.__members__]
    if unknown:
        raise ConfigError(f"{path}: unknown evolutions {unknown}. Known: {list(Evolution.__members__)}")
    return settings


def _style_sections(path: Path) -> dict[str, str]:
    """'## scenario' / '## task' / '## input_format' / '## expected_output_format' -> text."""
    sections: dict[str, str] = {}
    current = None
    for line in path.read_text().splitlines():
        heading = re.match(r"^##\s+(\w+)\s*$", line.strip())
        if heading:
            current = heading.group(1).lower()
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}
