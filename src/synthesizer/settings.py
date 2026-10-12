"""
Read and validate an agent's synthesizer settings (synth/synth.yaml, instructions.md, styles/*.md).
Errors are raised before generation, since a typo would otherwise silently change the test data.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.core.agent_config import Agent
from src.core.exceptions import ConfigError

STYLE_SECTIONS = ("scenario", "task", "additional_guidance", "input_format", "expected_output_format")
SETTINGS_KEYS = {"source", "per_source", "include_expected_answer", "instructions", "styles",
                 "evolutions", "quality_filter", "output"}
OUTPUT_KEYS = {"folder", "id", "case"}
# max_cases caps a style, taking documents from every group in turn; output is merged over `output:`.
STYLE_KEYS = {"file", "per_source", "question_type", "max_cases", "output"}


def load_settings(agent: Agent) -> dict[str, Any]:
    """Return synth.yaml as a validated dict, plus "folder": the agent's synth/ folder."""
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
        unknown_style = set(style or {}) - STYLE_KEYS
        if unknown_style:
            raise ConfigError(f"{path}: style '{name}' has unknown keys {sorted(unknown_style)} "
                              f"(allowed: {sorted(STYLE_KEYS)})")
        style_file = folder / str((style or {}).get("file", ""))
        if not style_file.is_file():
            raise ConfigError(f"{path}: style '{name}' file not found: {style_file}")
        style_sections(style_file)          # parse now so heading typos fail early
        if set((style or {}).get("output") or {}) - OUTPUT_KEYS:
            raise ConfigError(f"{path}: style '{name}' output: only has folder / id / case")
        cap = (style or {}).get("max_cases")
        if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap < 1):
            raise ConfigError(f"{path}: style '{name}' max_cases must be a whole number of 1 or more")
    if settings.get("instructions") and not (folder / settings["instructions"]).is_file():
        raise ConfigError(f"{path}: instructions file not found: {settings['instructions']}")
    check_evolutions(settings.get("evolutions") or {}, path)
    unknown_output = set(settings.get("output") or {}) - OUTPUT_KEYS
    if unknown_output:
        raise ConfigError(f"{path}: output: only has folder / id / case, not {sorted(unknown_output)}")

    settings["folder"] = folder
    return settings


def style_sections(path: Path) -> dict[str, str]:
    """Split a style file into its ## sections, e.g. {"task": "...", "scenario": "..."}.
    Unknown headings raise, so a typo can't silently merge into the previous section."""
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


def check_evolutions(evolutions: dict[str, Any], path: Path) -> None:
    """Check `evolutions:` (rounds + DeepEval weights): names known, weights >= 0 and summing to 1."""
    from deepeval.synthesizer.types import Evolution

    weights = {k: v for k, v in evolutions.items() if k != "rounds"}
    unknown = [k for k in weights if k not in Evolution.__members__]
    if unknown:
        raise ConfigError(f"{path}: unknown evolutions {unknown}. Known: {list(Evolution.__members__)}")
    if int(evolutions.get("rounds", 1)) < 0:
        raise ConfigError(f"{path}: evolutions.rounds must be 0 or more")
    if any(float(w) < 0 for w in weights.values()):
        raise ConfigError(f"{path}: evolution weights must not be negative")
    total = sum(float(w) for w in weights.values())
    if weights and abs(total - 1.0) > 0.01:
        raise ConfigError(f"{path}: evolution weights add up to {total:.2f}, they must add up to 1.0")
