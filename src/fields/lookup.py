"""
Lookup fields: values fetched by id with a function in agents/<agent>/lookups.py (e.g. page text).
Each id is fetched once per run and saved to outputs/lookups/<agent>/<lookup>/<id>.json; OFFLINE reuses saves.
If any id fails the field is empty and the case errors, so judges never score partial evidence.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from src.core import paths
from src.core.exceptions import ConfigError

FILE = "lookups.py"
_values: dict[tuple[str, str, str], Any] = {}      # (agent folder, lookup, id) -> value
_modules: dict[str, ModuleType] = {}


def check(folder: Path, name: str, where: str) -> None:
    """Raise ConfigError unless the agent's lookups.py exists and defines `name`."""
    if not (folder / FILE).is_file():
        raise ConfigError(f"{where}: lookup '{name}' needs {folder / FILE} with a function {name}(id)")
    if not callable(getattr(_module(folder), name, None)):
        raise ConfigError(f"{where}: {folder / FILE} has no function '{name}'")


def function(folder: Path, name: str) -> Callable[[str], Any]:
    """Return the agent's lookup function (tests patch this to avoid real calls)."""
    return getattr(_module(folder), name)


def texts(folder: Path, name: str, ids: list[Any], offline: bool, local: bool = False) -> tuple[list[str], list[str]]:
    """Return ([one text per id], [problems]); texts are [] if there is any problem."""
    out, problems = [], []
    for item in [str(i) for i in ids if str(i).strip()]:
        try:
            out.append(as_text(_value(folder, name, item, offline, local)))
        except Exception as exc:  # noqa: BLE001 — reported as the case's error, the run carries on
            problems.append(f"{name}({item}) failed: {type(exc).__name__}: {str(exc)[:200]}")
    return ([] if problems else out), problems


def as_text(value: Any) -> str:
    """Render a looked-up value as text: {title, text} -> 'title\\n\\ntext', other JSON indented."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "text" in value:
        return f"{value.get('title') or ''}\n\n{value['text']}".strip()
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def clear_cache() -> None:
    """Forget this run's looked-up values (for tests)."""
    _values.clear()


def _value(folder: Path, name: str, item: str, offline: bool, local: bool) -> Any:
    """Return one id's value: run cache, else saved copy (offline/local), else call the function and save."""
    key = (str(folder), name, item)
    if key in _values:
        return _values[key]
    saved = paths.OUTPUTS_DIR / "lookups" / folder.name / name / f"{_safe(item)}.json"
    if (offline or local) and saved.is_file():
        value = json.loads(saved.read_text())["value"]
    elif local:
        raise FileNotFoundError("no saved copy yet — a run (OFFLINE=1 is fine) looks it up")
    else:
        value = function(folder, name)(item)
        if value in (None, "", [], {}):
            raise ValueError(f"{name} returned nothing")
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"id": item, "value": value,
                                     "saved_at": datetime.now(UTC).isoformat(timespec="seconds")},
                                    indent=2, ensure_ascii=False, default=str) + "\n")
    _values[key] = value
    return value


def _module(folder: Path) -> ModuleType:
    """Import (once) and return the agent's lookups.py module."""
    path = folder / FILE
    if str(path) not in _modules:
        spec = importlib.util.spec_from_file_location(f"{folder.name}_lookups", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _modules[str(path)] = module
    return _modules[str(path)]


def _safe(item: str) -> str:
    """Make an id safe to use as a file name."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in item)
