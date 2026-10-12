"""
Deterministic checks from agents/<agent>/checks.yaml, run on the fields from fields.yaml.
Each check gives PASS / FAIL / SKIP. Checks can be nested under a group name: {group: {check: spec}}.

Field-only types:
  present       the field (or every one in `fields:`) has a value
  one_of        the value (or every list item) is in `values`
  equals        the field equals `other:` (a field) or `value:`
  min_words     the text has at least `min` words
  not_contains  the text contains none of `values`
  range         every field in `fields:` (or `field`) is a number in [`min`, `max`]
  same_count    every field in `fields:` has the same number of items
  subset        every item of the field is in `of:` (one or more fields)
  not_matches   the text of `field` / `fields:` matches none of the regex `patterns:` (case ignored)

Types comparing a field with the case's `expected` block (SKIP when the case has no value):
  any_in        at least one expected item is in the field
  contains      the field's text contains at least one expected item
  all_in        every expected item is in the field
  precision     share of the field's items that are expected >= threshold (default 0.7)
  recall        share of expected items found in the field >= threshold (default 0.7)
  ndcg          expected items rank near the top of the field (best first) >= threshold
  k: 5          only the first k items count
  expected: [a, b]   several expected keys combined
  compare: [{field: x, expected: a}, ...]   use the first pair the case has a value for
  Several ranked lists in one field: each item counts at its best position ([[a, b], [c]]: a, c 1st; b 2nd).

Options:
  diagnostic: true   shown, but never fails the case (targets still use its pass rate)
  when: {field: f, in: [..]} | {field: f, is: x} | {field: f, present: true} | {expected: key, is: x}
                     run only when the condition holds, else SKIP

Text compares ignore case and extra spaces.
"""

from __future__ import annotations

import math
import re
from typing import Any

from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP, Result
from src.fields.extract import is_empty

COMPARING = {"any_in", "all_in", "precision", "recall", "ndcg", "contains"}
TYPES = {"present", "one_of", "equals", "min_words", "not_contains", "range", "same_count", "subset",
         "not_matches"} | COMPARING
KEYS = {"type", "field", "fields", "expected", "compare", "values", "value", "other", "of", "min", "max",
        "threshold", "when", "description", "group", "k", "diagnostic", "patterns"}


def validate(checks: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """Validate checks.yaml and flatten groups. Returns {check name: spec}; grouped checks get `group:`."""
    flat: dict[str, dict[str, Any]] = {}
    for name, spec in (checks or {}).items():
        is_group = isinstance(spec, dict) and spec and "type" not in spec and all(
            isinstance(v, dict) for v in spec.values())
        for check_name, check_spec in (spec.items() if is_group else [(name, spec)]):
            if isinstance(check_spec, dict) and is_group:
                check_spec = {**check_spec, "group": name}
            problem = _problem(check_spec, defined_twice=check_name in flat)
            if problem:
                raise ConfigError(f"{where}: check '{check_name}' {problem}")
            flat[check_name] = dict(check_spec)
    clash = {s.get("group") for s in flat.values()} & set(flat)
    if clash:
        raise ConfigError(f"{where}: {sorted(clash)} used both as a group and as a check name")
    return flat


def _problem(spec: Any, defined_twice: bool) -> str:
    """Return what is wrong with one check spec, or '' when it is fine."""
    if not isinstance(spec, dict):
        return "must be a mapping like {type: present, field: answer}"
    if defined_twice:
        return "is defined twice"
    if set(spec) - KEYS:
        return f"has unknown keys {sorted(set(spec) - KEYS)} (allowed: {sorted(KEYS)})"
    if spec.get("type") not in TYPES:
        return f"needs type: one of {sorted(TYPES)} (got {spec.get('type')!r})"
    if spec["type"] in COMPARING and not (spec.get("compare") or (spec.get("field") and spec.get("expected"))):
        return "needs field: + expected: (or a compare: list)"
    return ""


def fields_read(spec: dict[str, Any]) -> set[str]:
    """Return the field names one check reads, so lookups run only when needed."""
    names = {spec.get("field"), spec.get("other"), (spec.get("when") or {}).get("field")}
    names |= set(_list(spec.get("fields"))) | set(_list(spec.get("of")))
    names |= {pair.get("field") for pair in spec.get("compare") or []}
    return {n for n in names if n}


def run_checks(checks: dict[str, dict[str, Any]], fields: dict[str, Any], case: dict[str, Any]) -> list[Result]:
    """Run every check and return one Result each, in written order."""
    expected = case.get("expected") or {}
    results = []
    for name, spec in checks.items():
        result = Result(name=name, kind="check", status=SKIP, group=spec.get("group", ""),
                        diagnostic=bool(spec.get("diagnostic")))
        result.reason = _when(spec.get("when"), fields, expected)
        if not result.reason:
            passed, reason = _check(spec, fields, expected, result)
            if passed is None:
                result.reason = reason
            else:
                result.status, result.reason = (PASS, "") if passed else (FAIL, reason)
        results.append(result)
    return results


def _check(spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any],
           result: Result) -> tuple[bool | None, str]:
    """Run one check; return (passed, reason). passed is None when the check is skipped."""
    name = spec.get("field")
    value = fields.get(name or "")
    many = spec.get("fields") or [name]
    match spec["type"]:
        case "present":
            empty = [n for n in many if is_empty(fields.get(n))]
            return not empty, f"{', '.join(empty)} empty"
        case "one_of":
            bad = [v for v in _items(value) if v not in _items(spec.get("values"))]
            return not is_empty(value) and not bad, f"{name}={value!r} not in {spec.get('values')}"
        case "equals":
            other = fields.get(spec["other"]) if "other" in spec else spec.get("value")
            label = spec.get("other", repr(spec.get("value")))
            return _norm(value) == _norm(other), f"{name}={value!r} != {label}={other!r}"
        case "min_words":
            words, minimum = len(str(value or "").split()), int(spec.get("min", 1))
            return words >= minimum, f"{name} has {words} words (< {minimum})"
        case "not_contains":
            found = [v for v in spec.get("values") or [] if _norm(v) in _norm(value)]
            return not found, f"{name} contains {found}"
        case "range":
            low, high = float(spec.get("min", 0)), float(spec.get("max", 1))
            problems = [_out_of_range(n, fields.get(n), low, high) for n in many]
            problems = [p for p in problems if p]
            return not problems, "; ".join(problems)
        case "same_count":
            counts = {n: len(_items(fields.get(n))) for n in spec.get("fields") or []}
            return len(set(counts.values())) <= 1, f"counts differ: {counts}"
        case "not_matches":
            text = "\n".join(str(item) for n in many for item in _list(fields.get(n)))
            found = [m.group(0) for pattern in spec.get("patterns") or []
                     for m in [re.search(pattern, text, re.IGNORECASE)] if m]
            return not found, f"found {found} in {', '.join(many)}"
        case "subset":
            allowed = [item for f in _items(spec.get("of")) for item in _items(fields.get(f))]
            extra = [v for v in _items(value) if v not in allowed]
            return not extra, f"{name} has {extra} not in {spec.get('of')}"
    return _compare(spec, fields, expected, result)


def _compare(spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any],
             result: Result) -> tuple[bool | None, str]:
    """Run a comparing check (any_in, contains, all_in, precision, recall, ndcg) against the case's expected."""
    pairs = spec.get("compare") or [{"field": spec.get("field"), "expected": spec.get("expected")}]
    for pair in pairs:
        want = list(dict.fromkeys(item for key in _list(pair.get("expected")) for item in _items(expected.get(key))))
        if want:
            break
    else:
        keys = [p.get("expected") for p in pairs]
        names = " or ".join("+".join(f"expected.{k}" for k in (ks if isinstance(ks, list) else [ks])) for ks in keys)
        return None, f"skipped: case has no {names}"
    name = pair["field"]
    if spec["type"] == "contains":
        text = _norm(" ".join(str(v) for v in _list(fields.get(name))))
        return (any(w in text for w in want),
                f"{name} has none of {want}" + (f": {text[:300]!r}" if text else " (it is empty)"))
    positions = _positions(fields.get(name))
    have = [item for item, position in positions.items() if not spec.get("k") or position <= int(spec["k"])]
    common = {w for w in want if w in have}
    match spec["type"]:
        case "any_in":
            return bool(common), f"none of {sorted(want)} in {name}={sorted(have)}"
        case "all_in":
            missing = [w for w in want if w not in have]
            return not missing, f"{name} lacks {missing}"
    if spec["type"] == "ndcg":
        result.threshold = float(spec.get("threshold", 0.7))
        result.score = ndcg(positions, want, int(spec.get("k", 5)))
        return (result.score >= result.threshold,
                f"ndcg {result.score:.2f} < {result.threshold}: expected={sorted(want)} found at "
                f"{ {w: positions.get(w, 'not found') for w in want} } (1 = first) in {name}={have}")
    base = have if spec["type"] == "precision" else want
    if not base:
        return None, f"skipped: {name} is empty"
    result.threshold = float(spec.get("threshold", 0.7))
    result.score = round(len(common) / len(set(base)), 4)
    return (result.score >= result.threshold,
            f"{spec['type']} {result.score:.2f} < {result.threshold}: {name}={sorted(have)} expected={sorted(want)}")


def ndcg(ranked: list[str] | dict[str, int], relevant: list[str], k: int = 5) -> float:
    """Binary-relevance NDCG@k (0..1, same as ranx). `ranked` is a best-first list or {item: position}."""
    positions = ranked if isinstance(ranked, dict) else {item: i for i, item in reversed(list(enumerate(ranked, 1)))}
    gain = sum(1 / math.log2(p + 1) for item, p in positions.items() if item in relevant and p <= k)
    best = sum(1 / math.log2(p + 1) for p in range(1, min(len(set(relevant)), k) + 1))
    return round(min(1.0, gain / best), 4) if best else 0.0


def _positions(value: Any) -> dict[str, int]:
    """Return {item: position (1 = first)}, best first; with several lists, each item's best position."""
    lists = [v for v in _list(value) if isinstance(v, list)] or [value]
    best: dict[str, int] = {}
    for ranked in lists:
        for position, item in enumerate(_items(ranked), 1):
            best[item] = min(position, best.get(item, position))
    return dict(sorted(best.items(), key=lambda pair: pair[1]))


def _when(condition: dict[str, Any] | None, fields: dict[str, Any], expected: dict[str, Any]) -> str:
    """Return '' when the `when:` condition holds, else the skip reason."""
    if not condition:
        return ""
    if "expected" in condition:
        value, label = expected.get(condition["expected"]), condition.get("field", f"expected.{condition['expected']}")
    else:
        value, label = fields.get(condition.get("field", "")), condition.get("field")
    if "in" in condition:
        holds = any(v in _items(condition["in"]) for v in _items(value))
    elif "is" in condition:
        holds = any(v == condition["is"] for v in (value if isinstance(value, list) else [value]))
    else:
        holds = (not is_empty(value)) == bool(condition.get("present", True))
    rule = ", ".join(f"{k} {v}" for k, v in condition.items() if k not in ("field", "expected"))
    return "" if holds else f"skipped: runs only when {label} {rule}"


def _items(value: Any) -> list[str]:
    """Return the value as a list of normalised, non-empty texts."""
    return [_norm(v) for v in _list(value) if not is_empty(v)]


def _list(value: Any) -> list[Any]:
    """Return the value as a list ([] when empty)."""
    return value if isinstance(value, list) else [] if is_empty(value) else [value]


def _norm(value: Any) -> str:
    """Lowercase and collapse whitespace."""
    return " ".join(str(value if value is not None else "").casefold().split())


def _out_of_range(name: str, value: Any, low: float, high: float) -> str:
    """Why `value` fails a range check, in words ("" when it is fine), e.g.
    'The agent took 85.8 s, over the 60 s limit' for latency_ms, 'score is 1.2, above the maximum of 1' otherwise."""
    if value is None or value == "" or value == []:
        return f"{name} is missing from the trace"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"{name} is not a number: {value!r}"
    if low <= value <= high:
        return ""
    if name.endswith("_ms"):                       # a duration in milliseconds: say it in seconds
        value, low, high, unit = value / 1000, low / 1000, high / 1000, " s"
    elif name.endswith(("_seconds", "_s")):
        unit = " s"
    else:
        unit = ""
    if unit:                                       # latency_ms -> "The agent", retrieval_seconds -> "Retrieval"
        what = re.sub(r"_(ms|seconds|s)$", "", name).replace("_", " ")
        what = "The agent" if what in ("latency", "duration", "response time", "elapsed") else what.capitalize()
        if value > high:
            return f"{what} took {_num(value)}{unit}, over the {_num(high)}{unit} limit"
        return f"{what} took {_num(value)}{unit}, under the {_num(low)}{unit} minimum"
    if value > high:
        return f"{name} is {_num(value)}, above the maximum of {_num(high)}"
    return f"{name} is {_num(value)}, below the minimum of {_num(low)}"


def _num(value: float) -> str:
    """85823.7 -> '85,823.7', 60.0 -> '60', 85.8237 -> '85.8'."""
    return f"{value:,.1f}".rstrip("0").rstrip(".")
