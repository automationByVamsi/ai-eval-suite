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
  athena    the text of the Athena pages whose ids are in the field named by `ids:` (one text per
            page), e.g. {from: athena, ids: evidence_page_ids} — see src/fields/evidence.py

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
from typing import Any

from src.core.exceptions import ConfigError
from src.fields.path import get, parse
from src.utils.text import strip_code_fence

SOURCES = ("state", "final", "node", "model", "message", "timing", "trace", "athena")
KEYS = {"from", "path", "node", "agent", "contains", "regex", "where", "pick", "matches", "flatten", "unique",
        "count", "first", "join", "default", "required", "description", "ids"}


def validate(fields: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """Check every field spec when the agent loads, so a typo fails at once — not halfway through a run."""
    checked: dict[str, dict[str, Any]] = {}
    for name, spec in (fields or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{where}: field '{name}' must be a mapping like {{from: state, path: ...}}")
        unknown = set(spec) - KEYS
        if unknown:
            raise ConfigError(f"{where}: field '{name}' has unknown keys {sorted(unknown)} (allowed: {sorted(KEYS)})")
        source = spec.get("from")
        if source not in SOURCES:
            raise ConfigError(f"{where}: field '{name}' needs from: one of {list(SOURCES)} (got {source!r})")
        if source == "node" and not spec.get("node"):
            raise ConfigError(f"{where}: field '{name}' (from: node) needs node: <part of the node name>")
        if source == "model" and not spec.get("agent"):
            raise ConfigError(f"{where}: field '{name}' (from: model) needs agent: <model agent name>")
        if source == "message" and not spec.get("contains"):
            raise ConfigError(f"{where}: field '{name}' (from: message) needs contains: <text in the message>")
        if source == "athena" and spec.get("ids") not in checked:
            raise ConfigError(f"{where}: field '{name}' (from: athena) needs ids: <a field above it with page ids>")
        for path in _paths(spec):
            parse(path)                                        # raises on an invalid path
        for other in (spec.get("where") or {}).values():
            if other not in checked:
                raise ConfigError(f"{where}: field '{name}' uses where: ...{other} — define '{other}' above it")
        if spec.get("regex"):
            re.compile(spec["regex"])
        checked[name] = spec
    return checked


def extract(trace: dict[str, Any], fields: dict[str, dict[str, Any]], offline: bool = False,
            fetch: set[str] | None = None, local: bool = False) -> tuple[dict[str, Any], list[str]]:
    """
    ({field: value}, [required fields that found nothing]). Never raises on odd trace content.
    offline: `from: athena` fields reuse saved page copies (pages never saved are still fetched).
    local:   `from: athena` fields use saved copies only, never Athena (make fields). Problems are listed
    under the key "_fetch_errors" (the runner reports them as an ERROR).
    fetch:   the `from: athena` fields to fetch (None: all). The runner passes only the ones the
             suite's judges and checks read, so e.g. a relevance-only suite never calls Athena.
    """
    view = TraceView(trace)
    values: dict[str, Any] = {}
    missing: list[str] = []
    for name, spec in fields.items():
        if spec["from"] == "athena" and fetch is not None and name not in fetch:
            value = None                                   # not needed by this suite: not fetched
        elif spec["from"] == "athena":
            from src.fields.evidence import page_texts
            value, problems = page_texts(_as_list(values.get(spec["ids"])), offline, local)
            if problems:
                values.setdefault("_fetch_errors", []).extend(f"{name}: {p}" for p in problems)
        else:
            value = field_value(view, spec, values)
        if is_empty(value) and "default" in spec:
            value = spec["default"]
        if is_empty(value) and spec.get("required"):
            missing.append(name)
        values[name] = value
    return values, missing


def field_value(view: TraceView, spec: dict[str, Any], earlier: dict[str, Any]) -> Any:
    """One field: its source, then path, where, pick and the other steps (see the top of this file)."""
    source = view.source(spec)
    value = _first_found(source, _paths(spec), many=spec["from"] in ("node", "model"))
    if spec.get("where"):
        value = [item for item in _as_list(value) if all(
            isinstance(item, dict) and _contains(earlier.get(other), item.get(key))
            for key, other in spec["where"].items())]
    if spec.get("pick"):
        value = [item.get(spec["pick"]) for item in _as_list(value) if isinstance(item, dict)]
        value = [v for v in value if v is not None]
    if spec.get("matches"):
        pattern = re.compile(spec["matches"], re.IGNORECASE)
        return any(pattern.search(str(v)) for v in _as_list(value))
    if spec.get("flatten"):
        value = [x for item in _as_list(value) for x in (item if isinstance(item, list) else [item])]
    if spec.get("unique"):
        value = list(dict.fromkeys(json.dumps(v, sort_keys=True, default=str) for v in _as_list(value)))
        value = [json.loads(v) for v in value]
    if spec.get("count"):
        return len(_as_list(value))
    if spec.get("first"):
        items = _as_list(value)
        value = items[0] if items else None
    if "join" in spec and isinstance(value, list):
        value = str(spec["join"]).join(str(v) for v in value)
    return value


class TraceView:
    """The sources of one trace, each worked out once (see `from` at the top of this file)."""

    def __init__(self, trace: dict[str, Any]) -> None:
        self.trace = trace or {}
        self.events = [e for e in self.trace.get("raw_events") or [] if isinstance(e, dict)]
        self._state: dict[str, Any] | None = None

    def source(self, spec: dict[str, Any]) -> Any:
        kind = spec["from"]
        if kind == "state":
            return self.state()
        if kind == "final":
            return self.final()
        if kind == "node":
            return [e["output"] for e in self.events if "output" in e and spec["node"] in _node_name(e)]
        if kind == "model":
            return [_json(t) for e in self.events if e.get("author") == spec["agent"] for t in _texts(e, "model")]
        if kind == "message":
            return self.message(spec["contains"], spec.get("regex"))
        if kind == "timing":
            return self.timing()
        return self.trace

    def state(self) -> dict[str, Any]:
        if self._state is None:
            self._state = {}
            for event in self.events:
                self._state.update(((event.get("actions") or {}).get("stateDelta")) or {})
        return self._state

    def final(self) -> Any:
        for event in reversed(self.events):
            targets = (event.get("nodeInfo") or {}).get("outputFor") or []
            if "output" in event and any("/" not in str(t) for t in targets):   # the top-level workflow
                return event["output"]
        output = _json(self.trace.get("agentOutput"))
        return output if isinstance(output, dict) else None

    def message(self, contains: str, regex: str | None) -> Any:
        found = [t for e in self.events for t in _texts(e) if contains in t]
        if not found:
            return None
        if not regex:
            return found[-1]
        match = re.search(regex, found[-1])
        return _number(match.group(1) if match.groups() else match.group(0)) if match else None

    def timing(self) -> dict[str, float]:
        """{step: seconds}: time from the end of the previous top-level step to the end of this one."""
        ends: dict[str, float] = {}
        start = None
        for event in self.events:
            stamp = event.get("timestamp")
            parts = str((event.get("nodeInfo") or {}).get("path") or "").split("/")
            if not isinstance(stamp, (int, float)) or len(parts) < 2:
                continue
            start = stamp if start is None else min(start, stamp)
            step = re.sub(r"@\d+$", "", parts[1])
            ends[step] = max(ends.get(step, stamp), stamp)
        seconds, previous = {}, start
        for step, end in sorted(ends.items(), key=lambda item: item[1]):
            seconds[step] = round(end - previous, 2)
            previous = end
        return seconds


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
        if many:
            value = [v for v in (get(item, path) for item in _as_list(source)) if v is not None]
        else:
            value = get(source, path)
        if not is_empty(value):
            return value
        if fallback is None:
            fallback = value
    return [] if many and fallback is None else fallback


def _node_name(event: dict[str, Any]) -> str:
    """'a@1/b@1/_anchor_branch_worker@2' -> '_anchor_branch_worker'."""
    last = str((event.get("nodeInfo") or {}).get("path") or "").split("/")[-1]
    return re.sub(r"@\d+$", "", last)


def _texts(event: dict[str, Any], role: str | None = None) -> list[str]:
    content = event.get("content") or {}
    if role and content.get("role") != role:
        return []
    return [str(p["text"]) for p in content.get("parts") or [] if isinstance(p, dict) and p.get("text")]


def _json(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(strip_code_fence(text))
    except json.JSONDecodeError:
        return text


def _number(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def _contains(container: Any, value: Any) -> bool:
    return value in container if isinstance(container, list) else value == container


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
