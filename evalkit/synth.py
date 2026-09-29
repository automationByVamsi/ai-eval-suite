"""
Synthesizer: generate test cases ("goldens") for any agent from source documents.

    SOURCE  ─►  GENERATOR  ─►  OUTPUT TEMPLATE
    where the documents     DeepEval Synthesizer, per      the JSON shape of this agent's
    come from (Athena,      document x style, judged by    test cases
    files, JSON, any API)   CORTEX, checked + de-duplicated

Everything for one agent lives in agents/<agent>/synth/:

    synth.yaml        source, styles, evolutions, quality filter, output template (see knowledge_agent)
    instructions.md   rules every generated question and answer must follow
    styles/*.md       one per question style: ## scenario / ## task / ## additional_guidance /
                      ## input_format / ## expected_output_format
    cache/            fetched documents (written by `make sources`, reused by `make goldens`)
    runs/             one manifest per generation run: counts, failures, skipped cases, files

Commands:
    make sources AGENT=.. [GROUP=..] [IDS=..]               fetch (or re-fetch) documents into cache/
    make goldens AGENT=.. [GROUP=..] [IDS=..] [REPLACE=1]   generate cases; fetches anything not cached
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from evalkit.config import Agent, ConfigError, load_agent
from evalkit.sources import load_source, normalise

STYLE_SECTIONS = ("scenario", "task", "additional_guidance", "input_format", "expected_output_format")
SETTINGS_KEYS = {"source", "per_source", "include_expected_answer", "instructions", "styles",
                 "evolutions", "quality_filter", "output"}
UNGROUPED = "Unassigned"
PLACEHOLDER_TEXT = re.compile(r"\[INSERT[^\]]*\]|(?<!\w)N/A(?!\w)|(?<!\w)TBD(?!\w)|\.\.\.", re.IGNORECASE)


# --- Commands -------------------------------------------------------------------------------

def fetch_sources(agent_name: str, groups: list[str] | None = None, ids: list[str] | None = None) -> list[Path]:
    """(Re-)fetch the selected documents from the source and save them in synth/cache/."""
    agent = load_agent(agent_name)
    settings = load_settings(agent)
    wanted, group_of = _select(settings, groups, ids)
    documents = _fetch(settings, wanted, group_of, groups)
    return [_save_cache(settings, d) for d in documents]


def generate_goldens(agent_name: str, groups: list[str] | None = None, ids: list[str] | None = None,
                     replace: bool = False) -> list[Path]:
    """Generate test cases for the selected documents and write them with the output template."""
    from deepeval.synthesizer import Synthesizer
    from deepeval.synthesizer.config import StylingConfig

    from evalkit.cortex import deepeval_llm

    agent = load_agent(agent_name)
    settings = load_settings(agent)
    documents = _documents(settings, groups, ids)
    output = {**_default_output(agent), **(settings.get("output") or {})}
    llm = deepeval_llm()
    started = datetime.now(timezone.utc)
    run = {"id": started.strftime("%Y%m%d_%H%M%S"), "generated_at": started.isoformat(timespec="seconds"),
           "date": started.date().isoformat(), "model": llm.get_model_name()}
    evolution_config, filtration_config = _deepeval_configs(settings, llm)
    include_expected = bool(settings.get("include_expected_answer", True))
    instructions = (settings["folder"] / settings["instructions"]).read_text().strip() \
        if settings.get("instructions") else ""

    planned: dict[Path, dict] = {}
    planned_ids: set[str] = set()
    seen_inputs: set[str] = set()
    failures, skipped = [], []
    for style_name, style in settings["styles"].items():
        sections = style_sections(settings["folder"] / style["file"])
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
                    path, case = _render_case(agent, output, run, style_name, document, golden,
                                              planned, planned_ids, replace)
                except _MissingGenerated as exc:
                    skipped.append({"source": document["id"], "style": style_name, "reason": str(exc)})
                    continue
                seen_inputs.add(_key(golden.input))
                planned[path] = case
                planned_ids.add(path.stem)
                made += 1
        print(f"Style {style_name}: {made} case(s) from {len(documents)} document(s)")

    # Only touch the test data once generation has finished.
    if replace:
        for folder in {p.parent for p in planned}:
            for old in folder.glob("*.json"):
                old.unlink()
    for path, case in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")

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


# --- Settings -------------------------------------------------------------------------------

def load_settings(agent: Agent) -> dict[str, Any]:
    folder = agent.folder / "synth"
    path = folder / "synth.yaml"
    if not path.is_file():
        raise ConfigError(f"{path} not found — copy agents/knowledge_agent/synth/ as a starting point")
    settings = yaml.safe_load(path.read_text()) or {}
    unknown = set(settings) - SETTINGS_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    if not (settings.get("source") or {}).get("type"):
        raise ConfigError(f"{path}: add a source: {{type: ...}} block")
    if not settings.get("styles"):
        raise ConfigError(f"{path}: add at least one style under styles:")
    for name, style in settings["styles"].items():
        style_file = folder / str((style or {}).get("file", ""))
        if not style_file.is_file():
            raise ConfigError(f"{path}: style '{name}' file not found: {style_file}")
        style_sections(style_file)
    if settings.get("instructions") and not (folder / settings["instructions"]).is_file():
        raise ConfigError(f"{path}: instructions file not found: {settings['instructions']}")
    _check_evolutions(settings.get("evolutions") or {}, path)
    unknown_output = set(settings.get("output") or {}) - {"folder", "id", "case"}
    if unknown_output:
        raise ConfigError(f"{path}: output: only has folder / id / case, not {sorted(unknown_output)}")
    settings["folder"] = folder
    return settings


def style_sections(path: Path) -> dict[str, str]:
    """Read a style file. Unknown '## headings' are an error, so a typo can't silently merge sections."""
    sections: dict[str, str] = {}
    current = None
    for line in path.read_text().splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if heading:
            current = heading.group(1).strip().lower()
            if current not in STYLE_SECTIONS:
                raise ConfigError(f"{path}: unknown section '## {heading.group(1)}'. Use: {list(STYLE_SECTIONS)}")
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}


def _check_evolutions(evolutions: dict[str, Any], path: Path) -> None:
    from deepeval.synthesizer.types import Evolution

    weights = {k: v for k, v in evolutions.items() if k != "rounds"}
    unknown = [k for k in weights if k not in Evolution.__members__]
    if unknown:
        raise ConfigError(f"{path}: unknown evolutions {unknown}. Known: {list(Evolution.__members__)}")
    if int(evolutions.get("rounds", 1)) < 0:
        raise ConfigError(f"{path}: evolutions.rounds must be 0 or more")
    if any(float(w) < 0 for w in weights.values()):
        raise ConfigError(f"{path}: evolution weights must not be negative")
    if weights and abs(sum(float(w) for w in weights.values()) - 1.0) > 0.01:
        raise ConfigError(f"{path}: evolution weights add up to {sum(float(w) for w in weights.values()):.2f}, "
                          f"they must add up to 1.0")


def _deepeval_configs(settings: dict[str, Any], llm: Any) -> tuple[Any, Any]:
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
        critic_model=llm,                                # without this DeepEval would call OpenAI
    )
    return evolution, filtration


# --- Documents ------------------------------------------------------------------------------

def _select(settings: dict[str, Any], groups: list[str] | None, ids: list[str] | None
            ) -> tuple[list[str] | None, dict[str, str]]:
    """Which document ids to use (None = all the source has) and each id's group, from ids_file."""
    group_of: dict[str, str] = {}
    ids_file = settings["source"].get("ids_file")
    if ids_file:
        path = settings["folder"] / ids_file
        for entry in json.loads(path.read_text()):
            name = entry.get("group") or entry.get("domain") or UNGROUPED
            for doc_id in entry.get("ids") or entry.get("page_ids") or []:
                group_of[str(doc_id)] = name
        if groups:
            known = {g.lower() for g in group_of.values()}
            missing = [g for g in groups if g.lower() not in known]
            if missing:
                raise ConfigError(f"{path}: unknown group(s) {missing}. Groups: {sorted(set(group_of.values()))}")
    if ids:
        return [str(i) for i in ids], group_of
    if ids_file:
        wanted = [i for i, g in group_of.items() if not groups or g.lower() in {x.lower() for x in groups}]
        return wanted, group_of
    return None, group_of


def _fetch(settings: dict[str, Any], wanted: list[str] | None, group_of: dict[str, str],
           groups: list[str] | None) -> list[dict[str, Any]]:
    source = load_source(settings["source"]["type"])
    documents = []
    for raw in source.fetch(settings["source"], wanted, settings["folder"]):
        document = normalise(raw, f"source {settings['source']['type']}")
        document["group"] = group_of.get(document["id"]) or document["group"] or UNGROUPED
        if not groups or document["group"].lower() in {g.lower() for g in groups}:
            documents.append(document)
    return documents


def _documents(settings: dict[str, Any], groups: list[str] | None, ids: list[str] | None) -> list[dict[str, Any]]:
    """Cached documents, fetching the ones that aren't cached yet."""
    wanted, group_of = _select(settings, groups, ids)
    if wanted is None:                       # e.g. a folder of files: always read the current files
        documents = _fetch(settings, None, group_of, groups)
    else:
        cache = settings["folder"] / "cache"
        missing = [i for i in wanted if not (cache / f"{_safe(i)}.json").is_file()]
        if missing:
            print(f"Fetching {len(missing)} document(s) not in the cache: {missing}")
            for document in _fetch(settings, missing, group_of, None):
                _save_cache(settings, document)
        documents = []
        for doc_id in wanted:
            path = cache / f"{_safe(doc_id)}.json"
            if not path.is_file():
                raise ConfigError(f"Source returned no document for id {doc_id}")
            document = json.loads(path.read_text())
            document["group"] = group_of.get(doc_id) or document.get("group") or UNGROUPED
            documents.append(document)
    if not documents:
        raise ConfigError("No documents selected — check the source settings, GROUP and IDS")
    return documents


def _save_cache(settings: dict[str, Any], document: dict[str, Any]) -> Path:
    path = settings["folder"] / "cache" / f"{_safe(document['id'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved {path} ({len(document['text'])} characters)")
    return path


# --- Output template ------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.]*)(?::([^{}]*))?\}")
_ROOTS = ("generated", "source", "style", "group", "group_slug", "run", "agent", "id", "n")


class _MissingGenerated(Exception):
    """The generated text doesn't contain a field the template asks for — the case is skipped."""


def _default_output(agent: Agent) -> dict[str, Any]:
    """Used for any part of `output:` an agent leaves out: the standard evaluation test case."""
    return {
        "folder": "testdata/golden/{style}/{group_slug}",
        "id": "SYN_{style}_{group_slug}_{n:03}",
        "case": {
            "test_case_id": "{id}",
            "description": "Generated ({style}) from {source.id} {source.title}",
            "input": {agent.input_field: "{generated.input}"},
            "expected": {"expected_answer": "{generated.expected_output}", "source_id": "{source.id}"},
            "metadata": {"origin": "SYNTHETIC", "approval_status": "UNREVIEWED", "style": "{style}",
                         "group": "{group}", "generation_run_id": "{run.id}",
                         "generated_at": "{run.generated_at}", "generator_model": "{run.model}"},
        },
    }


def _render_case(agent: Agent, output: dict[str, Any], run: dict[str, Any], style: str,
                 document: dict[str, Any], golden: Any, planned: dict[Path, dict], planned_ids: set[str],
                 replace: bool) -> tuple[Path, dict[str, Any]]:
    context = {
        "generated": {"input": golden.input, "expected_output": golden.expected_output or ""},
        "source": document, "style": style, "group": document["group"], "group_slug": _slug(document["group"]),
        "run": run, "agent": {"name": agent.name, "input_field": agent.input_field},
    }
    folder = agent.folder / str(render(output["folder"], context))
    n = 0
    while True:
        n += 1
        case_id = str(render(output["id"], {**context, "n": n}))
        path = folder / f"{_safe(case_id)}.json"
        taken = path in planned or path.stem in planned_ids or (path.exists() and not replace)
        if not taken:
            break
        if n > 9999:
            raise ConfigError(f"Output template id '{output['id']}' never gives a free name — include {{n}} in it")
    case = render(output["case"], {**context, "n": n, "id": case_id})
    return path, case


def render(template: Any, context: dict[str, Any]) -> Any:
    """Fill {placeholders} in every string. A string that is exactly one placeholder keeps its type."""
    if isinstance(template, dict):
        return {key: render(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render(value, context) for value in template]
    if not isinstance(template, str):
        return template
    whole = _PLACEHOLDER.fullmatch(template)
    if whole and not whole.group(2):
        return _lookup(whole.group(1), context)
    return _PLACEHOLDER.sub(lambda m: format(_lookup(m.group(1), context) or "", m.group(2) or ""), template)


def _lookup(path: str, context: dict[str, Any]) -> Any:
    root, *rest = path.split(".")
    if root not in _ROOTS:
        raise ConfigError(f"Output template: unknown placeholder '{{{path}}}'. Start with one of {list(_ROOTS)}")
    value = context.get(root)
    for part in rest:
        if isinstance(value, str):           # generated text asked to be JSON, e.g. {generated.input.request}
            try:
                value = json.loads(_strip_fence(value))
            except json.JSONDecodeError:
                value = None
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif root == "generated":
            raise _MissingGenerated(f"generated text has no '{path}'")
        else:
            return None                       # optional source/run details, e.g. source.metadata.revision
    return value


# --- Small helpers --------------------------------------------------------------------------

def _problem(golden: Any, include_expected: bool, seen: set[str]) -> str:
    question, answer = (golden.input or "").strip(), (golden.expected_output or "").strip()
    if not question:
        return "empty generated input"
    if include_expected and not answer:
        return "empty generated expected output"
    for label, text in (("input", question), ("expected output", answer)):
        if PLACEHOLDER_TEXT.search(text):
            return f"placeholder text in {label}: {text[:80]!r}"
    if _key(question) in seen:
        return "duplicate question"
    return ""


def _key(text: str) -> str:
    return " ".join((text or "").lower().split())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "unassigned"


def _safe(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_")


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()
