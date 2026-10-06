"""
Pull named fields out of a trace, as described in agents/<agent>/fields.yaml — no Python per agent.

    fields:
      answer:          {from: final, path: answer.summary, required: true}
      anchor_page_ids: {from: state, path: evidence_set.anchor_page_ids}

Each field says WHERE to look (`from`) and WHAT to take there (`path`, see src/fields/path.py).

`from` — the part of the trace to look in:
  state     the agent's session state: every event's actions.stateDelta merged in order, so the
            latest value of each key wins (ADK repeats state in many events; early copies are empty)
  final     the workflow's final output: the `output` of the event whose nodeInfo.outputFor names
            the top-level workflow (falls back to agentOutput when that is a JSON object)
  node      the `output` of every event from nodes whose name contains `node:` (e.g. parallel
            branch workers _anchor_branch_worker@1, @2, ...) — always a list, one item per event
  model     the JSON reply of every model event written by `agent:` — always a list
  message   status text written by the workflow: the last text containing `contains:`, or the first
            group of `regex:` in it (numbers become numbers)
  timing    seconds spent in each top-level workflow step, from the event timestamps
  trace     the saved trace file itself (agentOutput, latency_ms, sessionId, ...)
  lookup    values from outside the trace, looked up by id with a function the agent provides in
            agents/<agent>/lookups.py: one text per id in the field named by `ids:`, e.g.
            {from: lookup, lookup: get_page_content_from_athena, ids: evidence_page_ids}
            — see src/fields/lookup.py

Then, in this order (all optional):
  path: a.b           or a list of paths: the first one that finds something wins (handy when a
                      trace format changes: list the new path first, keep the old one after it)
  where: {k: field}   keep list items whose key k is in (or equals) another field's value
  pick: key           take that key from every item
  matches: regex      True if any value matches the regex (case-insensitive)
  flatten: true       one level of nested lists -> one list
  unique: true        drop repeats, keep order
  count: true         the number of items
  first: true         the first item only
  join: "\\n"          a list -> one text
  default: <value>    used when nothing was found
  required: true      nothing found -> the case is an ERROR ("the trace changed?"), not a skip

Fields are computed top to bottom, so `where:` can use any field defined above it.
Preview what every field gives for a saved trace:  make fields AGENT=<agent> CASE=<case_id>
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.core.exceptions import ConfigError
from src.fields.path import get, parse
from src.utils.text import strip_code_fence

SOURCES = ("state", "final", "node", "model", "message", "timing", "trace", "lookup")
KEYS = {"from", "path", "node", "agent", "contains", "regex", "where", "pick", "matches", "flatten", "unique",
        "count", "first", "join", "default", "required", "description", "ids", "lookup"}

# The key some sources need, and what to write there (for the error message).
SOURCE_NEEDS = {
    "node": ("node", "<part of the node name>"),
    "model": ("agent", "<model agent name>"),
    "message": ("contains", "<text in the message>"),
}


# --- loading: check fields.yaml once, when the agent loads ---------------------------------------

def validate(fields: dict[str, Any], where: str, folder: Path | None = None) -> dict[str, dict[str, Any]]:
    """
    Check every field spec when the agent loads, so a typo fails at once — not halfway through a run.
    folder: the agent's folder, where `from: lookup` functions live (agents/<agent>/lookups.py).
    """
    checked: dict[str, dict[str, Any]] = {}
    for name, spec in (fields or {}).items():
        checked[name] = _validate_field(name, spec, checked, where, folder)
    return checked


def _validate_field(name: str, spec: Any, earlier: dict[str, Any], where: str, folder: Path | None) -> dict:
    """One field spec, checked. `earlier`: the fields defined above it (the only ones it may refer to)."""
    label = f"{where}: field '{name}'"
    if not isinstance(spec, dict):
        raise ConfigError(f"{label} must be a mapping like {{from: state, path: ...}}")
    unknown = set(spec) - KEYS
    if unknown:
        raise ConfigError(f"{label} has unknown keys {sorted(unknown)} (allowed: {sorted(KEYS)})")
    source = spec.get("from")
    if source not in SOURCES:
        raise ConfigError(f"{label} needs from: one of {list(SOURCES)} (got {source!r})")
    if source in SOURCE_NEEDS:
        key, hint = SOURCE_NEEDS[source]
        if not spec.get(key):
            raise ConfigError(f"{label} (from: {source}) needs {key}: {hint}")
    if source == "lookup":
        spec = _validate_lookup(label, spec, earlier, where, folder)
    for path in _paths(spec):
        parse(path)                                        # raises on an invalid path
    for other in (spec.get("where") or {}).values():
        if other not in earlier:
            raise ConfigError(f"{label} uses where: ...{other} — define '{other}' above it")
    if spec.get("regex"):
        re.compile(spec["regex"])
    return spec


def _validate_lookup(label: str, spec: dict, earlier: dict[str, Any], where: str, folder: Path | None) -> dict:
    """A `from: lookup` field: its ids field is above it and its function exists in lookups.py."""
    if spec.get("ids") not in earlier:
        raise ConfigError(f"{label} (from: lookup) needs ids: <a field above it with the ids>")
    if not spec.get("lookup"):
        raise ConfigError(f"{label} (from: lookup) needs lookup: <function in lookups.py>")
    if folder is None:
        raise ConfigError(f"{label} (from: lookup) needs the agent's folder")
    from src.fields import lookup
    lookup.check(folder, spec["lookup"], where)
    return {**spec, "_folder": folder}


# --- extracting: every field of one trace ----------------------------------------------------------

def extract(trace: dict[str, Any], fields: dict[str, dict[str, Any]], offline: bool = False,
            fetch: set[str] | None = None, local: bool = False) -> tuple[dict[str, Any], list[str]]:
    """
    ({field: value}, [required fields that found nothing]). Never raises on odd trace content.
    offline: `from: lookup` fields reuse saved copies (ids never saved are still looked up).
    local:   `from: lookup` fields use saved copies only, never a real call (make fields). Problems are listed
    under the key "_fetch_errors" (the runner reports them as an ERROR).
    fetch:   the `from: lookup` fields to compute (None: all). The runner passes only the ones the
             suite's judges and checks read, so e.g. a relevance-only suite never looks anything up.
    """
    view = TraceView(trace)
    values: dict[str, Any] = {}
    missing: list[str] = []
    for name, spec in fields.items():
        if spec["from"] != "lookup":
            value = field_value(view, spec, values)
        elif fetch is None or name in fetch:
            value = _looked_up(name, spec, values, offline, local)
        else:
            value = None                                   # not needed by this suite: not looked up
        if is_empty(value) and "default" in spec:
            value = spec["default"]
        if is_empty(value) and spec.get("required"):
            missing.append(name)
        values[name] = value
    return values, missing


def _looked_up(name: str, spec: dict[str, Any], values: dict[str, Any], offline: bool, local: bool) -> Any:
    """A `from: lookup` field: one text per id. Problems go to values["_fetch_errors"]."""
    from src.fields import lookup
    ids = _as_list(values.get(spec["ids"]))
    texts, problems = lookup.texts(spec["_folder"], spec["lookup"], ids, offline, local)
    if problems:
        values.setdefault("_fetch_errors", []).extend(f"{name}: {p}" for p in problems)
    if texts and "join" in spec:                           # e.g. one text for a judge's answer
        return spec["join"].join(texts)
    return texts


def field_value(view: TraceView, spec: dict[str, Any], earlier: dict[str, Any]) -> Any:
    """One field: its source, then path, then each step in the order listed at the top of this file."""
    value = _first_found(view.source(spec), _paths(spec), many=spec["from"] in ("node", "model"))
    if spec.get("where"):
        value = _keep_where(value, spec["where"], earlier)
    if spec.get("pick"):
        value = _pick(value, spec["pick"])
    if spec.get("matches"):
        return _matches(value, spec["matches"])            # a yes / no answer: no step after it applies
    if spec.get("flatten"):
        value = _flatten(value)
    if spec.get("unique"):
        value = _unique(value)
    if spec.get("count"):
        return len(_as_list(value))                        # a number: no step after it applies
    if spec.get("first"):
        value = _first(value)
    if "join" in spec and isinstance(value, list):
        value = str(spec["join"]).join(str(v) for v in value)
    return value


# The steps, one small function each (see the top of this file).

def _keep_where(value: Any, where: dict[str, str], earlier: dict[str, Any]) -> list[Any]:
    """Keep the items whose key k is in (or equals) the value of an earlier field, for every k in where:."""
    def keep(item: Any) -> bool:
        return isinstance(item, dict) and all(_contains(earlier.get(other), item.get(key))
                                              for key, other in where.items())
    return [item for item in _as_list(value) if keep(item)]


def _pick(value: Any, key: str) -> list[Any]:
    """That key from every item (items without it are dropped)."""
    picked = [item.get(key) for item in _as_list(value) if isinstance(item, dict)]
    return [v for v in picked if v is not None]


def _matches(value: Any, pattern: str) -> bool:
    regex = re.compile(pattern, re.IGNORECASE)
    return any(regex.search(str(v)) for v in _as_list(value))


def _flatten(value: Any) -> list[Any]:
    return [x for item in _as_list(value) for x in (item if isinstance(item, list) else [item])]


def _unique(value: Any) -> list[Any]:
    """Drop repeats, keep order (works for dicts and lists too: compared as JSON)."""
    seen = dict.fromkeys(json.dumps(v, sort_keys=True, default=str) for v in _as_list(value))
    return [json.loads(v) for v in seen]


def _first(value: Any) -> Any:
    items = _as_list(value)
    return items[0] if items else None


# --- the trace's sources ---------------------------------------------------------------------------

class TraceView:
    """The sources of one trace, each worked out once (see `from` at the top of this file)."""

    def __init__(self, trace: dict[str, Any]) -> None:
        self.trace = trace or {}
        self.events = [e for e in self.trace.get("raw_events") or [] if isinstance(e, dict)]
        self._state: dict[str, Any] | None = None

    def source(self, spec: dict[str, Any]) -> Any:
        """The part of the trace a field's `from:` names."""
        match spec["from"]:
            case "state":
                return self.state()
            case "final":
                return self.final()
            case "node":
                return self.node_outputs(spec["node"])
            case "model":
                return self.model_replies(spec["agent"])
            case "message":
                return self.message(spec["contains"], spec.get("regex"))
            case "timing":
                return self.timing()
            case _:                                        # "trace": the saved trace file itself
                return self.trace

    def state(self) -> dict[str, Any]:
        """Every event's stateDelta merged in order: the latest value of each key wins."""
        if self._state is None:
            self._state = {}
            for event in self.events:
                self._state.update(((event.get("actions") or {}).get("stateDelta")) or {})
        return self._state

    def final(self) -> Any:
        """The output of the top-level workflow (else agentOutput, when that is a JSON object)."""
        for event in reversed(self.events):
            targets = (event.get("nodeInfo") or {}).get("outputFor") or []
            if "output" in event and any("/" not in str(t) for t in targets):   # the top-level workflow
                return _unwrap(event["output"])
        output = _json(self.trace.get("agentOutput"))
        return output if isinstance(output, dict) else None

    def node_outputs(self, node: str) -> list[Any]:
        """The output of every event from a node whose name contains `node`."""
        return [e["output"] for e in self.events if "output" in e and node in _node_name(e)]

    def model_replies(self, agent: str) -> list[Any]:
        """Every model reply written by `agent`, parsed as JSON when it is JSON."""
        return [_json(text) for e in self.events if e.get("author") == agent for text in _texts(e, "model")]

    def message(self, contains: str, regex: str | None) -> Any:
        """The last text containing `contains`; with `regex:`, its first group (numbers become numbers)."""
        found = [t for e in self.events for t in _texts(e) if contains in t]
        if not found:
            return None
        if not regex:
            return found[-1]
        match = re.search(regex, found[-1])
        if not match:
            return None
        return _number(match.group(1) if match.groups() else match.group(0))

    def timing(self) -> dict[str, float]:
        """{step: seconds}: time from the end of the previous top-level step to the end of this one."""
        start, ends = self._step_ends()
        seconds, previous = {}, start
        for step, end in sorted(ends.items(), key=lambda item: item[1]):
            seconds[step] = round(end - previous, 2)
            previous = end
        return seconds

    def _step_ends(self) -> tuple[float | None, dict[str, float]]:
        """(first timestamp, {top-level step: its last timestamp})."""
        start, ends = None, {}
        for event in self.events:
            stamp = event.get("timestamp")
            parts = str((event.get("nodeInfo") or {}).get("path") or "").split("/")
            if not isinstance(stamp, (int, float)) or len(parts) < 2:
                continue
            start = stamp if start is None else min(start, stamp)
            step = re.sub(r"@\d+$", "", parts[1])
            ends[step] = max(ends.get(step, stamp), stamp)
        return start, ends


# --- helpers -----------------------------------------------------------------------------------

def _paths(spec: dict[str, Any]) -> list[str]:
    path = spec.get("path", "")
    return [str(p) for p in path] if isinstance(path, list) else [str(path)]


def _first_found(source: Any, paths: list[str], many: bool) -> Any:
    """
    The first path that finds something non-empty. Otherwise the first value that exists at all
    (e.g. caveats: [] stays [] — "present but empty" — instead of None, "not in the trace").
    For node/model sources the path runs on every item.
    """
    fallback = None
    for path in paths:
        value = _get_each(source, path) if many else get(source, path)
        if not is_empty(value):
            return value
        if fallback is None:
            fallback = value
    return [] if many and fallback is None else fallback


def _get_each(items: Any, path: str) -> list[Any]:
    """The path on every item (items where it finds nothing are dropped)."""
    return [v for v in (get(item, path) for item in _as_list(items)) if v is not None]


def _node_name(event: dict[str, Any]) -> str:
    """'a@1/b@1/_anchor_branch_worker@2' -> '_anchor_branch_worker'."""
    last = str((event.get("nodeInfo") or {}).get("path") or "").split("/")[-1]
    return re.sub(r"@\d+$", "", last)


def _texts(event: dict[str, Any], role: str | None = None) -> list[str]:
    """The text parts of an event's content (only for `role`, when given)."""
    content = event.get("content") or {}
    if role and content.get("role") != role:
        return []
    return [str(p["text"]) for p in content.get("parts") or [] if isinstance(p, dict) and p.get("text")]


def _json(text: Any) -> Any:
    """Parsed JSON when `text` is JSON (code fences allowed), else `text` unchanged."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(strip_code_fence(text))
    except json.JSONDecodeError:
        return text


def _number(text: str) -> Any:
    """'3' -> 3, '2.5' -> 2.5, anything else unchanged."""
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def _contains(container: Any, value: Any) -> bool:
    return value in container if isinstance(container, list) else value == container


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _unwrap(output: Any) -> Any:
    """
    Newer traces wrap the final output in an envelope: {"response_type": "answer", "answer": {question_type,
    answer, confidence, caveats, user_warnings, evidence}}. Return the inner object, so `from: final`
    paths work for both shapes; response_type is kept alongside.
    """
    inner = output.get("answer") if isinstance(output, dict) and "response_type" in output else None
    if isinstance(inner, dict) and "answer" in inner:
        return {"response_type": output["response_type"], **inner}
    return output
