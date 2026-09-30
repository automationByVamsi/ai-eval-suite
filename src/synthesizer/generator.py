"""
The synthesizer commands.

  make sources AGENT=.. [GROUP=..] [IDS=..]               fetch_sources():   (re)fetch documents into synth/cache/
  make goldens AGENT=.. [GROUP=..] [IDS=..] [REPLACE=1]   generate_goldens(): generate test cases

generate_goldens(), for every style x document:
  1. DeepEval's Synthesizer writes question(s) + reference answer(s), with the CORTEX model
     (style sections + instructions.md as its styling, evolutions + quality filter from synth.yaml)
  2. each golden is checked: not empty, no placeholder text like [INSERT ...], not a duplicate
  3. the output template turns it into this agent's test case JSON
Files are written only after all generation succeeded, so a crash never leaves half a data set.
A manifest in synth/runs/ records what was generated, skipped (and why) and what failed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.clients import cortex_client
from src.core.agent_config import load_agent
from src.synthesizer.documents import documents_for_generation, fetch, save_to_cache, select
from src.synthesizer.output_template import MissingGenerated, default_output, render_case
from src.synthesizer.settings import load_settings, style_sections
from src.utils.text import normalised

# Text a model writes when it didn't have the information: such cases are dropped.
PLACEHOLDER_TEXT = re.compile(r"\[INSERT[^\]]*\]|(?<!\w)N/A(?!\w)|(?<!\w)TBD(?!\w)|\.\.\.", re.IGNORECASE)


def fetch_sources(agent_name: str, groups: list[str] | None = None, ids: list[str] | None = None) -> list[Path]:
    """(Re-)fetch the selected documents from the source and save them in synth/cache/."""
    settings = load_settings(load_agent(agent_name))
    wanted, group_of = select(settings, groups, ids)
    return [save_to_cache(settings, d) for d in fetch(settings, wanted, group_of, groups)]


def generate_goldens(agent_name: str, groups: list[str] | None = None, ids: list[str] | None = None,
                     replace: bool = False) -> list[Path]:
    """Generate test cases for the selected documents and write them with the output template."""
    from deepeval.synthesizer import Synthesizer  # imported here: DeepEval is slow to import
    from deepeval.synthesizer.config import StylingConfig

    agent = load_agent(agent_name)
    settings = load_settings(agent)
    documents = documents_for_generation(settings, groups, ids)
    output = {**default_output(agent), **(settings.get("output") or {})}
    llm = cortex_client.deepeval_llm()
    started = datetime.now(UTC)
    run = {"id": started.strftime("%Y%m%d_%H%M%S"), "generated_at": started.isoformat(timespec="seconds"),
           "date": started.date().isoformat(), "model": llm.get_model_name()}
    evolution_config, filtration_config = _deepeval_configs(settings, llm)
    include_expected = bool(settings.get("include_expected_answer", True))
    instructions = (settings["folder"] / settings["instructions"]).read_text().strip() \
        if settings.get("instructions") else ""

    planned: dict[Path, dict] = {}          # file -> case, written at the end
    seen_inputs: set[str] = set()           # for duplicate detection across styles
    failures, skipped = [], []
    for style_name, style in settings["styles"].items():
        sections = style_sections(settings["folder"] / style["file"])
        # DeepEval's StylingConfig has four fields; our extra sections are folded into them.
        task = "\n\n".join(s for s in [sections.get("task"), sections.get("additional_guidance")] if s)
        scenario = "\n\n".join(s for s in [sections.get("scenario"), instructions] if s)
        synthesizer = Synthesizer(
            model=llm, async_mode=False, evolution_config=evolution_config, filtration_config=filtration_config,
            styling_config=StylingConfig(
                scenario=scenario or None, task=task or None,
                input_format=sections.get("input_format") or None,
                expected_output_format=sections.get("expected_output_format") or None,
            ),
        )
        per_source = int(style.get("per_source", settings.get("per_source", 1)))
        made = 0
        for document in documents:
            try:
                goldens = synthesizer.generate_goldens_from_contexts(
                    contexts=[[document["text"]]], source_files=[document["id"]],
                    include_expected_output=include_expected, max_goldens_per_context=per_source)
            except Exception as exc:  # noqa: BLE001 — one bad document must not stop the run
                failures.append({"source": document["id"], "style": style_name,
                                 "error": f"{type(exc).__name__}: {exc}"})
                print(f"  ERROR {style_name} / {document['id']}: {exc}")
                continue
            for golden in goldens:
                problem = _problem(golden, include_expected, seen_inputs)
                if problem:
                    skipped.append({"source": document["id"], "style": style_name, "reason": problem})
                    continue
                try:
                    path, case = render_case(agent, output, run, style_name, document, golden,
                                             set(planned), replace)
                except MissingGenerated as exc:
                    skipped.append({"source": document["id"], "style": style_name, "reason": str(exc)})
                    continue
                seen_inputs.add(normalised(golden.input))
                planned[path] = case
                made += 1
        print(f"Style {style_name}: {made} case(s) from {len(documents)} document(s)")

    _write_cases(planned, replace)
    manifest = settings["folder"] / "runs" / f"{run['id']}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "run": run, "agent": agent.name, "source": settings["source"],
        "documents": [d["id"] for d in documents], "styles": list(settings["styles"]),
        "generated": len(planned), "skipped": skipped, "failed": failures,
        "files": [str(p.relative_to(agent.folder)) for p in planned],
    }, indent=2, ensure_ascii=False))
    print(f"{len(planned)} generated, {len(skipped)} skipped, {len(failures)} failed.  Manifest: {manifest}")
    if planned:
        print("Review the cases (metadata.approval_status), then run them as a suite, e.g. SUITE=golden")
    return list(planned)


def _write_cases(planned: dict[Path, dict], replace: bool) -> None:
    """Write the new cases. With REPLACE=1, first clear the folders they go into."""
    if replace:
        for folder in {p.parent for p in planned}:
            for old in folder.glob("*.json"):
                old.unlink()
    for path, case in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")


def _deepeval_configs(settings: dict[str, Any], llm: Any) -> tuple[Any, Any]:
    """DeepEval's EvolutionConfig and FiltrationConfig from `evolutions:` and `quality_filter:`."""
    from deepeval.synthesizer.config import EvolutionConfig, FiltrationConfig
    from deepeval.synthesizer.types import Evolution

    evolutions = dict(settings.get("evolutions") or {})
    rounds = int(evolutions.pop("rounds", 1))
    weights = {Evolution[name]: float(weight) for name, weight in evolutions.items()}
    evolution = (EvolutionConfig(num_evolutions=rounds, evolutions=weights) if weights
                 else EvolutionConfig(num_evolutions=rounds))               # DeepEval's default mix
    quality = settings.get("quality_filter") or {}
    filtration = FiltrationConfig(
        synthetic_input_quality_threshold=float(quality.get("min_quality", 0.5)),
        max_quality_retries=int(quality.get("retries", 3)),
        critic_model=llm,               # without this DeepEval would call OpenAI
    )
    return evolution, filtration


def _problem(golden: Any, include_expected: bool, seen: set[str]) -> str:
    """Why a generated golden can't be used, or "" when it's fine."""
    question, answer = (golden.input or "").strip(), (golden.expected_output or "").strip()
    if not question:
        return "empty generated input"
    if include_expected and not answer:
        return "empty generated expected output"
    for label, text in (("input", question), ("expected output", answer)):
        if PLACEHOLDER_TEXT.search(text):
            return f"placeholder text in {label}: {text[:80]!r}"
    if normalised(question) in seen:
        return "duplicate question"
    return ""
