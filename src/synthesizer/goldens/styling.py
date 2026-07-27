"""Build DeepEval StylingConfig from markdown style files."""

from __future__ import annotations

import re
from pathlib import Path

from deepeval.synthesizer.config import StylingConfig


def parse_style_md(path: Path) -> dict[str, str]:
    """Parse ## scenario / ## task / ## input_format / ## expected_output_format."""
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^##\s+(\w+)\s*$", line.strip())
        if heading:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = heading.group(1).lower()
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def build_styling_config(
    style_file: Path,
    *,
    shared_instructions: str | None = None,
) -> StylingConfig:
    """
    One style markdown → one StylingConfig.

    Shared instructions.md (domain rules) are folded into scenario so every
    style still respects grounding / advisor tone rules.
    """
    sections = parse_style_md(style_file) if style_file.is_file() else {}
    scenario = sections.get("scenario", "")
    if shared_instructions and shared_instructions.strip():
        scenario = (
            f"{scenario}\n\nShared instructions:\n{shared_instructions.strip()}".strip()
            if scenario
            else f"Shared instructions:\n{shared_instructions.strip()}"
        )
    return StylingConfig(
        scenario=scenario or None,
        task=sections.get("task") or None,
        input_format=sections.get("input_format") or None,
        expected_output_format=sections.get("expected_output_format") or None,
    )
