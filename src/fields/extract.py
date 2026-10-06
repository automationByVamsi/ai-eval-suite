"""
Read named fields out of an agent trace, as listed in agents/<agent>/fields.yaml.

Step 1. The trace is turned into ONE simple JSON document (see `view()` below):

    final     the agent's final output (what the caller receives)
    state     the agent's session state (every event's stateDelta merged; the latest value wins)
    nodes     {node name: [the output of each event from that node]}
    models    {agent name: [each model reply of that agent, as JSON when it is JSON]}
    messages  [every text written in the trace, in order]
    timing    {workflow step: seconds}
    trace     the saved trace file itself (latency_ms, agentOutput, ...)

Step 2. Every field is a JMESPath query on that document (try it on https://jmespath.org):

    fields:
      answer_type:     final.question_type
      anchor_page_ids: state.evidence_set.anchor_page_ids
      cited_titles:    final.evidence[].title

Options, when a field needs more than a path:
    path: [a, b]         a list of paths: the first one that finds something wins
    where: {k: field}    keep the items whose key k is in an earlier field's value
    pick: key            then take that key from each item
    unique: true         drop repeated values
    join: "\\n"           a list -> one text
    default: <value>     used when nothing was found
    required: true       nothing found -> the case is an ERROR ("has the trace format changed?")
    lookup: fn, ids: f   not in the trace: call fn(id) in agents/<agent>/lookups.py for each id in field f

Preview every field on a saved trace:  make fields AGENT=<agent> CASE=<case_id>
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jmespath

from src.core.exceptions import ConfigError
from src.utils.text import strip_code_fence

KEYS = {"path", "where", "pick", "unique", "join", "default", "required", "lookup", "ids", "description"}


def validate(fields: dict[str, Any], where: str, folder: Path | None = None) -> dict[str, dict[str, Any]]:
    """Check fields.yaml when the agent loads, so a typo fails at once. A plain string is a path."""
    checked: dict[str, dict[str, Any]] = {}
    for name, spec in (fields or {}).items():
        spec = {"path": spec} if isinstance(spec, str) else spec
        problem = _problem(spec, checked, folder, where)
        if problem:
            raise ConfigError(f"{where}: field '{name}' {problem}")
        checked[name] = {**spec, "_folder": folder} if "lookup" in spec else spec
    return checked


def _problem(spec: Any, earlier: dict[str, Any], folder: Path | None, where: str) -> str:
    """What is wrong with one field ('' when it is fine)."""
    if not isinstance(spec, dict):
        return "must be a path, or a mapping like {path: final.answer, required: true}"
    if "from" in spec:
        return "uses the old {from: x, path: y} form: write path: x.y (see src/fields/extract.py)"
    if set(spec) - KEYS:
        return f"has unknown keys {sorted(set(spec) - KEYS)} (allowed: {sorted(KEYS)})"
    if "lookup" in spec:
        if spec.get("ids") not in earlier:
            return "needs ids: <a field above it with the ids>"
        from src.fields import lookup
        lookup.check(folder, spec["lookup"], where)          # lookups.py has that function
        return ""
    if not spec.get("path"):
        return "needs path:"
    for path in _as_list(spec["path"]):
        try:
            jmespath.compile(str(path))
        except jmespath.exceptions.JMESPathError as exc:
            return f"has an invalid path {path!r}: {exc}"
    missing = [f for f in (spec.get("where") or {}).values() if f not in earlier]
    return f"uses where: {missing} — define them above it" if missing else ""


def extract(trace: dict[str, Any], fields: dict[str, dict[str, Any]], offline: bool = False,
            fetch: set[str] | None = None, local: bool = False) -> tuple[dict[str, Any], list[str]]:
    """
    ({field: value}, [required fields that found nothing]). Never raises on odd trace content.
    Lookup fields: only those in `fetch` (None: all); offline reuses saved copies; local never calls anything.
    Lookup problems are listed under values["_fetch_errors"] (the runner reports them as an ERROR).
    """
    document = view(trace)
    values: dict[str, Any] = {}
    missing: list[str] = []
    for name, spec in fields.items():
        if "lookup" in spec:
            value = _lookup(name, spec, values, offline, local) if fetch is None or name in fetch else None
        else:
            value = _find(document, spec, values)
        if isinstance(value, list) and "join" in spec:
            value = str(spec["join"]).join(str(v) for v in value)
        if is_empty(value) and "default" in spec:
            value = spec["default"]
        if is_empty(value) and spec.get("required"):
            missing.append(name)
        values[name] = value
    return values, missing


def _find(document: dict[str, Any], spec: dict[str, Any], earlier: dict[str, Any]) -> Any:
    """The field's path(s), then where: / pick: / unique: when the field has them."""
    found = [_search(path, document) for path in _as_list(spec["path"])]
    value = next((v for v in found if not is_empty(v)), next((v for v in found if v is not None), None))
    if spec.get("where"):
        value = [item for item in _as_list(value) if isinstance(item, dict)
                 and all(_has(earlier.get(field), item.get(key)) for key, field in spec["where"].items())]
    if spec.get("pick"):
        value = [item[spec["pick"]] for item in _as_list(value)
                 if isinstance(item, dict) and item.get(spec["pick"]) is not None]
    if spec.get("unique"):
        seen = dict.fromkeys(json.dumps(v, sort_keys=True, default=str) for v in _as_list(value))
        value = [json.loads(v) for v in seen]
    return value


def _search(path: str, document: dict[str, Any]) -> Any:
    try:
        return jmespath.search(str(path), document)
    except jmespath.exceptions.JMESPathError:       # e.g. join() on something that isn't text
        return None


def _lookup(name: str, spec: dict[str, Any], values: dict[str, Any], offline: bool, local: bool) -> list[str]:
    from src.fields import lookup
    texts, problems = lookup.texts(spec["_folder"], spec["lookup"], _as_list(values.get(spec["ids"])), offline, local)
    if problems:
        values.setdefault("_fetch_errors", []).extend(f"{name}: {p}" for p in problems)
    return texts


# --- the trace as one document ----------------------------------------------------------------

def view(trace: dict[str, Any]) -> dict[str, Any]:
    """The trace as one JSON document: final, state, nodes, models, messages, timing, trace (see top)."""
    trace = trace or {}
    events = [e for e in trace.get("raw_events") or [] if isinstance(e, dict)]
    document = {"final": _final(events, trace), "state": {}, "nodes": {}, "models": {}, "messages": [],
                "timing": _timing(events), "trace": trace}
    for event in events:
        content = event.get("content") or {}
        texts = [str(p["text"]) for p in content.get("parts") or [] if isinstance(p, dict) and p.get("text")]
        document["state"].update((event.get("actions") or {}).get("stateDelta") or {})
        document["messages"] += texts
        if "output" in event:
            document["nodes"].setdefault(_node_name(event), []).append(event["output"])
        if content.get("role") == "model" and event.get("author"):
            document["models"].setdefault(event["author"], []).extend(_json(t) for t in texts)
    return document


def _final(events: list[dict[str, Any]], trace: dict[str, Any]) -> Any:
    """The output of the top-level workflow (else agentOutput, when that is a JSON object)."""
    for event in reversed(events):
        targets = (event.get("nodeInfo") or {}).get("outputFor") or []
        if "output" in event and any("/" not in str(t) for t in targets):
            return _unwrap(event["output"])
    output = _json(trace.get("agentOutput"))
    return output if isinstance(output, dict) else None


def _unwrap(output: Any) -> Any:
    """Newer traces wrap the answer: {response_type, answer: {answer, evidence, ...}} -> the inner object."""
    inner = output.get("answer") if isinstance(output, dict) and "response_type" in output else None
    if isinstance(inner, dict) and "answer" in inner:
        return {"response_type": output["response_type"], **inner}
    return output


def _timing(events: list[dict[str, Any]]) -> dict[str, float]:
    """{top-level step: seconds from the end of the previous step to the end of this one}."""
    start, ends = None, {}
    for event in events:
        stamp, parts = event.get("timestamp"), str((event.get("nodeInfo") or {}).get("path") or "").split("/")
        if isinstance(stamp, (int, float)) and len(parts) > 1:
            start = stamp if start is None else min(start, stamp)
            step = re.sub(r"@\d+$", "", parts[1])
            ends[step] = max(ends.get(step, stamp), stamp)
    seconds, previous = {}, start
    for step, end in sorted(ends.items(), key=lambda item: item[1]):
        seconds[step], previous = round(end - previous, 2), end
    return seconds


def _node_name(event: dict[str, Any]) -> str:
    """'a@1/b@1/_anchor_branch_worker@2' -> '_anchor_branch_worker'."""
    return re.sub(r"@\d+$", "", str((event.get("nodeInfo") or {}).get("path") or "").split("/")[-1])


# --- small helpers ----------------------------------------------------------------------------

def _json(text: Any) -> Any:
    """Parsed JSON when `text` is JSON (code fences allowed), else `text` unchanged."""
    try:
        return json.loads(strip_code_fence(text)) if isinstance(text, str) else text
    except json.JSONDecodeError:
        return text


def _has(container: Any, value: Any) -> bool:
    return value in container if isinstance(container, list) else value == container


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
