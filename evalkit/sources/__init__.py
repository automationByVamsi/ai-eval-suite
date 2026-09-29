"""
Synthesizer sources: where the documents that test cases are generated from come from.

A source is a Python file with one function:

    def fetch(settings: dict, ids: list[str] | None, folder: Path) -> list[dict]:
        '''Return documents. ids=None means "everything you have".'''

and every document it returns looks like this (only id and text are required):

    {"id": "36626", "title": "...", "text": "readable text", "group": "Recoveries Commercial Bank",
     "metadata": {"revision": "..."}}

`settings` is the `source:` block of the agent's synth.yaml; `folder` is the agent's synth/ folder
(resolve relative paths against it).

Where sources are looked up, by `source: {type: <name>}`:
    sources/<name>.py           the team's own sources at the repo root (e.g. athena_mcp)
    evalkit/sources/<name>.py   built-ins: files, json_records
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from evalkit.config import ROOT, ConfigError

BUILT_IN = Path(__file__).parent
TEAM = ROOT / "sources"


def load_source(name: str) -> ModuleType:
    for folder in (TEAM, BUILT_IN):
        path = folder / f"{name}.py"
        if path.is_file() and not name.startswith("_"):
            spec = importlib.util.spec_from_file_location(f"source_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "fetch"):
                raise ConfigError(f"{path} has no fetch(settings, ids, folder) function")
            return module
    available = sorted({p.stem for f in (TEAM, BUILT_IN) if f.is_dir() for p in f.glob("*.py")
                        if not p.stem.startswith("_")})
    raise ConfigError(f"Unknown source type '{name}'. Available: {available}")


def normalise(document: dict, where: str) -> dict:
    """Check a document from a source and fill the optional keys."""
    if not str(document.get("id") or "").strip() or not str(document.get("text") or "").strip():
        raise ValueError(f"{where}: every document needs a non-empty 'id' and 'text'")
    return {
        "id": str(document["id"]).strip(),
        "title": str(document.get("title") or ""),
        "text": str(document["text"]).strip(),
        "group": str(document.get("group") or ""),
        "metadata": dict(document.get("metadata") or {}),
    }
