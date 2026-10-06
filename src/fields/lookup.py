"""
Values looked up OUTSIDE the trace, by id, with a function the agent provides — e.g. the text of
the pages the agent used, which the trace names by id only (fields.yaml):

    contexts: {lookup: get_page_content_from_athena, ids: evidence_page_ids}

`lookup:` is a function in agents/<agent>/lookups.py that takes one id and returns its value:
a text, a {"title", "text"} mapping, or any JSON (e.g. a record from the agent's own API). Where
the value comes from, and how it is cleaned, is the agent's business; this file knows nothing
about Athena, HTML or pages. It only does what every agent needs, for every id in the `ids:` field:

  1. already looked up in this run?        reuse it (each id is looked up once per run)
  2. saved by an earlier run?              OFFLINE=1 reuses the saved copy (a live run looks it up
                                           again, so a changed source is picked up)
  3. otherwise                             call the agent's function, save a copy
Saved copies: outputs/lookups/<agent>/<lookup>/<id>.json  ({id, value, saved_at}).

OFFLINE=1 means "replay the agent's saved trace"; ids never saved are still looked up once.
`make fields` (local=True) never calls anything: it only shows saved copies.

The field's value is one text per id (a {"title", "text"} value becomes "title\\n\\ntext"; other
JSON is shown as indented JSON). If any id fails, the field is left empty and the reason is
reported, so the case shows an ERROR — a judge never scores on partial evidence.
The runner only computes lookup fields that the suite's judges or checks read.
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
_values: dict[tuple[str, str, str], Any] = {}      # (agent folder, lookup, id) -> value, for this run
_modules: dict[str, ModuleType] = {}


def check(folder: Path, name: str, where: str) -> None:
    """At agent load: agents/<agent>/lookups.py exists and defines `name`."""
    if not (folder / FILE).is_file():
        raise ConfigError(f"{where}: lookup '{name}' needs {folder / FILE} with a function {name}(id)")
    if not callable(getattr(_module(folder), name, None)):
        raise ConfigError(f"{where}: {folder / FILE} has no function '{name}'")


def function(folder: Path, name: str) -> Callable[[str], Any]:
    """The agent's lookup function (tests replace this to avoid real calls)."""
    return getattr(_module(folder), name)


def texts(folder: Path, name: str, ids: list[Any], offline: bool, local: bool = False) -> tuple[list[str], list[str]]:
    """([one text per id], [problems]). With any problem the texts are [] (no partial evidence)."""
    out, problems = [], []
    for item in [str(i) for i in ids if str(i).strip()]:
        try:
            out.append(as_text(_value(folder, name, item, offline, local)))
        except Exception as exc:  # noqa: BLE001 — reported as the case's error, the run carries on
            problems.append(f"{name}({item}) failed: {type(exc).__name__}: {str(exc)[:200]}")
    return ([] if problems else out), problems


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "text" in value:
        return f"{value.get('title') or ''}\n\n{value['text']}".strip()
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def clear_cache() -> None:
    """Forget this run's looked-up values (tests; a new process starts empty anyway)."""
    _values.clear()


def _value(folder: Path, name: str, item: str, offline: bool, local: bool) -> Any:
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
    path = folder / FILE
    if str(path) not in _modules:
        spec = importlib.util.spec_from_file_location(f"{folder.name}_lookups", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _modules[str(path)] = module
    return _modules[str(path)]


def _safe(item: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in item)
