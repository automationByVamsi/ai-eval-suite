"""
Synthesizer sources: where the documents that test cases are generated from come from.

A source is one Python file in this folder, named after its `type:` in synth.yaml, with one function:

    def fetch(settings: dict, ids: list[str] | None, folder: Path) -> list[dict]:
        '''Return documents. ids=None means "everything you have".'''

  settings   the `source:` block of the agent's synth.yaml
  folder     the agent's synth/ folder (resolve relative paths against it)

Every document it returns looks like this (only id and text are required):

    {"id": "36626", "title": "...", "text": "readable text", "group": "Recoveries Commercial Bank",
     "metadata": {"revision": "..."}}

Available: athena_mcp (Hive Athena pages), files (a folder of .txt/.md/.json), json_records
(one JSON file of records). To add a source — an API, a database export — copy json_records.py.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from src.core.exceptions import ConfigError

HERE = Path(__file__).parent


def available() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.py") if not p.stem.startswith("_"))


def load_source(name: str) -> ModuleType:
    """The source module for `source: {type: <name>}`."""
    if name not in available():
        raise ConfigError(f"Unknown source type '{name}'. Available: {available()}")
    module = importlib.import_module(f"{__name__}.{name}")
    if not hasattr(module, "fetch"):
        raise ConfigError(f"{HERE / name}.py has no fetch(settings, ids, folder) function")
    return module


def normalise(document: dict[str, Any], where: str) -> dict[str, Any]:
    """Check one document from a source and fill in the optional keys."""
    if not str(document.get("id") or "").strip() or not str(document.get("text") or "").strip():
        raise ValueError(f"{where}: every document needs a non-empty 'id' and 'text'")
    return {
        "id": str(document["id"]).strip(),
        "title": str(document.get("title") or ""),
        "text": str(document["text"]).strip(),
        "group": str(document.get("group") or ""),
        "metadata": dict(document.get("metadata") or {}),
    }
