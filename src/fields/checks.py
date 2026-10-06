"""
Deterministic checks, written in agents/<agent>/checks.yaml, run on the fields from fields.yaml.
Each check gives one PASS / FAIL / SKIP result.

    checks:
      answer:                                   # a group (the dashboard shows checks by group)
        answer_min_words: {type: min_words, field: answer, min: 8}
        confidence_valid: {type: one_of, field: confidence, values: [HIGH, MEDIUM, LOW]}
      retrieval:
        anchor_hit:       {type: any_in, field: anchor_page_ids, expected: expected_anchor_page_ids}

Types that look at the trace's fields only:
  present       the field has a value (with fields: [...], every one of them)
  one_of        the value (or every item of a list) is one of `values`
  equals        the field equals `other:` (another field) or `value:`
  min_words     the text has at least `min` words
  not_contains  the text contains none of `values`
  range         every field in `fields:` (or `field`) is a number between `min` and `max`
  same_count    every field in `fields:` has the same number of items
  subset        every item of the field is in `of:` (one or more fields, combined)

Types that compare a field with the test case's `expected` block (SKIP when the case has no value):
  any_in        at least one expected item is in the field             (e.g. anchor hit)
  all_in        every expected item is in the field
  precision     share of the field's items that are expected  >= threshold (default 0.7)
  recall        share of the expected items in the field      >= threshold (default 0.7)
    k: 5                    only the first 5 items of the field count (precision@5 on a ranked list)
    expected: [a, b]        the values of several expected keys together
    compare: [{field: x, expected: a}, {field: y, expected: b}]   the first pair the case has a value for

Run a check only sometimes (else SKIP):
    when: {field: confidence, in: [MEDIUM, LOW]}      when: {field: metadata_missing, is: true}
    when: {field: cited_page_ids, present: true}      when: {expected: should_decline, is: true}

Text is compared ignoring case and extra spaces ("How To  Add" == "how to add").
"""

from __future__ import annotations

from typing import Any

from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP, Result
from src.fields.extract import is_empty

COMPARING = {"any_in", "all_in", "precision", "recall"}
TYPES = {"present", "one_of", "equals", "min_words", "not_contains", "range", "same_count", "subset"} | COMPARING
KEYS = {"type", "field", "fields", "expected", "compare", "values", "value", "other", "of", "min", "max",
        "threshold", "when", "description", "group", "k"}


def validate(checks: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """Check checks.yaml when the agent loads. Returns {check name: spec}; grouped checks get `group:`."""
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
    """What is wrong with one check ('' when it is fine)."""
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
    """The fields one check reads (so lookups run only when a check needs them)."""
    names = {spec.get("field"), spec.get("other"), (spec.get("when") or {}).get("field")}
    names |= set(_list(spec.get("fields"))) | set(_list(spec.get("of")))
    names |= {pair.get("field") for pair in spec.get("compare") or []}
    return {n for n in names if n}


def run_checks(checks: dict[str, dict[str, Any]], fields: dict[str, Any], case: dict[str, Any]) -> list[Result]:
    """One Result per check, in the order they are written."""
    expected = case.get("expected") or {}
    results = []
    for name, spec in checks.items():
        result = Result(name=name, kind="check", status=SKIP, group=spec.get("group", ""))
        result.reason = _when(spec.get("when"), fields, expected)
        if not result.reason:
            passed, reason = _check(spec, fields, expected, result)
            if passed is None:
                result.reason = reason                                   # skipped
            else:
                result.status, result.reason = (PASS, "") if passed else (FAIL, reason)
        results.append(result)
    return results


def _check(spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any],
           result: Result) -> tuple[bool | None, str]:
    """(passed, reason if it failed). passed is None when the check is skipped."""
    name = spec.get("field")
    value = fields.get(name or "")
    many = spec.get("fields") or [name]                     # checks that can read several fields
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
            bad = {n: fields.get(n) for n in many
                   if not isinstance(fields.get(n), (int, float)) or not low <= fields.get(n) <= high}
            return not bad, f"not numbers in [{low}, {high}]: {bad}"
        case "same_count":
            counts = {n: len(_items(fields.get(n))) for n in spec.get("fields") or []}
            return len(set(counts.values())) <= 1, f"counts differ: {counts}"
        case "subset":
            allowed = [item for f in _items(spec.get("of")) for item in _items(fields.get(f))]
            extra = [v for v in _items(value) if v not in allowed]
            return not extra, f"{name} has {extra} not in {spec.get('of')}"
    return _compare(spec, fields, expected, result)


def _compare(spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any],
             result: Result) -> tuple[bool | None, str]:
    """any_in / all_in / precision / recall: the field's items against the case's expected items."""
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
    have = _items(fields.get(name))[: int(spec["k"])] if spec.get("k") else _items(fields.get(name))
    common = {w for w in want if w in have}
    match spec["type"]:
        case "any_in":
            return bool(common), f"none of {sorted(want)} in {name}={sorted(have)}"
        case "all_in":
            missing = [w for w in want if w not in have]
            return not missing, f"{name} lacks {missing}"
    base = have if spec["type"] == "precision" else want         # precision: of what was found; recall: of expected
    if not base:
        return None, f"skipped: {name} is empty"
    result.threshold = float(spec.get("threshold", 0.7))
    result.score = round(len(common) / len(set(base)), 4)
    return (result.score >= result.threshold,
            f"{spec['type']} {result.score:.2f} < {result.threshold}: {name}={sorted(have)} expected={sorted(want)}")


def _when(condition: dict[str, Any] | None, fields: dict[str, Any], expected: dict[str, Any]) -> str:
    """'' when the check should run, else why it is skipped. Reads a field, or a key of the case's expected."""
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
    """Anything -> a list of normalised texts, so ids and titles compare cleanly."""
    return [_norm(v) for v in _list(value) if not is_empty(v)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if is_empty(value) else [value]


def _norm(value: Any) -> str:
    return " ".join(str(value if value is not None else "").casefold().split())
