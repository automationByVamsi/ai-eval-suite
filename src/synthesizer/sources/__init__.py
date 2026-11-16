"""
Synthesizer sources: plugins that supply the documents test cases are generated from.

A source is a file here named after its synth.yaml `type:`, defining
fetch(settings, ids, folder) -> list of {"id", "text", "title"?, "group"?, "metadata"?}.
ids=None means "everything"; folder is the agent's synth/ folder. Copy json_records.py to start.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from src.core.exceptions import ConfigError

HERE = Path(__file__).parent


def available() -> list[str]:
    """Return the names of the source modules in this folder."""
    return sorted(p.stem for p in HERE.glob("*.py") if not p.stem.startswith("_"))


def load_source(name: str) -> ModuleType:
    """Import and return the source module for `source: {type: <name>}`."""
    if name not in available():
        raise ConfigError(f"Unknown source type '{name}'. Available: {available()}")
    module = importlib.import_module(f"{__name__}.{name}")
    if not hasattr(module, "fetch"):
        raise ConfigError(f"{HERE / name}.py has no fetch(settings, ids, folder) function")
    return module


def normalise(document: dict[str, Any], where: str) -> dict[str, Any]:
    """Validate one document from a source and fill in its optional keys."""
    if not str(document.get("id") or "").strip() or not str(document.get("text") or "").strip():
        raise ValueError(f"{where}: every document needs a non-empty 'id' and 'text'")
    return {
        "id": str(document["id"]).strip(),
        "title": str(document.get("title") or ""),
        "text": str(document["text"]).strip(),
        "group": str(document.get("group") or ""),
        "metadata": dict(document.get("metadata") or {}),
    }
