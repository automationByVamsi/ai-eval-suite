"""
Deterministic checks written in YAML (`checks:` in agents/<agent>/agent.yaml), run on the fields
from fields.yaml. Each produces one pass / fail / skip result, like a parser.py check.

    checks:
      confidence_valid:   {type: one_of, field: confidence, values: [HIGH, MEDIUM, LOW]}
      anchor_hit:         {type: any_in, field: anchor_page_ids, expected: expected_anchor_page_ids}
      fallback_disclosed: {type: present, field: disclosures, when: {field: metadata_missing, is: true}}

Types:
  present       the field has a value (not empty)
  one_of        the value (or every item of a list) is one of `values`
  equals        the field equals `other:` (another field) or `value:`
  min_words     the text has at least `min` words
  not_contains  the text contains none of `values`
  range         every field in `fields:` is a number between `min` and `max`
  same_count    every field in `fields:` has the same number of items
  subset        every item of the field is in `of:` (one or more fields, combined)
  any_in        at least one expected item is in the field                 (e.g. anchor hit)
  all_in        every expected item is in the field
  precision     |field ∩ expected| / |field|     >= threshold (default 0.7); SKIP when the field is empty
  recall        |field ∩ expected| / |expected|  >= threshold (default 0.7)

`expected:` is a key in the test case's "expected" block. When a case has no value for it, the
check is SKIPPED (never guessed). To accept one of several ways of labelling, list them in
`compare:` — the first pair whose expected value the case has is used:
      compare:
        - {field: anchor_page_ids, expected: expected_anchor_page_ids}
        - {field: anchor_titles,   expected: expected_anchor_page_titles}
Text is compared ignoring case and extra spaces, so "How to Add a support need" matches
"How To Add a Support Need".

Checks can be grouped (the group name shows on the dashboard, and a suite can pick whole groups):
      checks:
        citations:
          citations_in_evidence_set: {type: subset, field: cited_page_ids, of: [anchor_page_ids]}
        retrieval:
          anchor_hit: {type: any_in, field: anchor_page_ids, expected: expected_anchor_page_ids}
Which checks a suite runs: `checks:` under the suite (all | none | [group or check names]),
see src/core/agent_config.py.

`when:` runs the check only if a condition holds, else SKIP:
      when: {field: confidence, in: [MEDIUM, LOW]}     the value is one of these
      when: {field: metadata_missing, is: true}         the value (or any item of a list) is true
      when: {field: cited_page_ids, present: true}      the field has a value
"""

from __future__ import annotations

from typing import Any

from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP, Result
from src.fields.extract import is_empty

TYPES = {"present", "one_of", "equals", "min_words", "not_contains", "range", "same_count", "subset",
         "any_in", "all_in", "precision", "recall"}
KEYS = {"type", "field", "fields", "expected", "compare", "values", "value", "other", "of", "min", "max",
        "threshold", "when", "description", "group"}
COMPARING = {"any_in", "all_in", "precision", "recall"}


def validate(checks: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """
    Check the `checks:` section when the agent loads. Returns one flat {name: spec}; a check written
    inside a group gets `group: <group name>`.
    """
    flat: dict[str, dict[str, Any]] = {}
    for name, spec in (checks or {}).items():
        if _is_group(spec):
            for check_name, check_spec in spec.items():
                _add(flat, check_name, {**check_spec, "group": name}, where)
        else:
            _add(flat, name, spec, where)
    groups = {spec.get("group") for spec in flat.values()} - {None}
    clash = groups & set(flat)
    if clash:
        raise ConfigError(f"{where}: {sorted(clash)} used both as a group and as a check name")
    return flat


def _is_group(spec: Any) -> bool:
    return (isinstance(spec, dict) and "type" not in spec and bool(spec)
            and all(isinstance(v, dict) for v in spec.values()))


def _add(flat: dict[str, dict[str, Any]], name: str, spec: Any, where: str) -> None:
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: check '{name}' must be a mapping like {{type: present, field: answer}}")
    if name in flat:
        raise ConfigError(f"{where}: check '{name}' is defined twice")
    unknown = set(spec) - KEYS
    if unknown:
        raise ConfigError(f"{where}: check '{name}' has unknown keys {sorted(unknown)} (allowed: {sorted(KEYS)})")
    if spec.get("type") not in TYPES:
        raise ConfigError(f"{where}: check '{name}' needs type: one of {sorted(TYPES)} (got {spec.get('type')!r})")
    if spec["type"] in COMPARING and not (spec.get("compare") or (spec.get("field") and spec.get("expected"))):
        raise ConfigError(f"{where}: check '{name}' needs field: + expected: (or a compare: list)")
    flat[name] = dict(spec)


def fields_read(spec: dict[str, Any]) -> set[str]:
    """The fields.yaml fields one check reads (used to run lookups only when needed)."""
    names = {spec.get("field"), spec.get("other"), (spec.get("when") or {}).get("field")}
    names |= set(_as_names(spec.get("fields"))) | set(_as_names(spec.get("of")))
    names |= {pair.get("field") for pair in spec.get("compare") or []}
    return {n for n in names if n}


def _as_names(value: Any) -> list[str]:
    return value if isinstance(value, list) else [value] if value else []


def run_checks(checks: dict[str, dict[str, Any]], fields: dict[str, Any], case: dict[str, Any]) -> list[Result]:
    """One Result per check, in the order they are written."""
    expected = case.get("expected") or {}
    return [_one(name, spec, fields, expected) for name, spec in checks.items()]


def _one(name: str, spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any]) -> Result:
    result = Result(name=name, kind="check", status=SKIP, group=spec.get("group", ""))
    skip_reason = _when(spec.get("when"), fields)
    if skip_reason:
        result.reason = skip_reason
        return result
    kind = spec["type"]
    value = fields.get(spec.get("field", ""))

    if kind in COMPARING:
        pair = _pair(spec, expected)
        if pair is None:
            result.reason = f"skipped: case has no {_expected_names(spec)}"
            return result
        field_name, want = pair
        have = _items(fields.get(field_name))
        common = [w for w in want if w in have]
        if kind in ("precision", "recall"):
            base = have if kind == "precision" else want
            if not base:
                result.reason = f"skipped: {field_name} is empty"
                return result
            result.threshold = float(spec.get("threshold", 0.7))
            result.score = round(len({*common}) / len({*base}), 4)
            passed = result.score >= result.threshold
            detail = (f"{kind} {result.score:.2f} < {result.threshold}: "
                      f"{field_name}={sorted(have)} expected={sorted(want)}")
        elif kind == "any_in":
            passed, detail = bool(common), f"none of {sorted(want)} in {field_name}={sorted(have)}"
        else:
            missing = [w for w in want if w not in have]
            passed, detail = not missing, f"{field_name} lacks {missing}"
        return _done(result, passed, detail)

    if kind == "present":
        return _done(result, not is_empty(value), f"{spec['field']} is empty")
    if kind == "one_of":
        allowed = _items(spec.get("values"))
        bad = [v for v in _items(value) if v not in allowed]
        return _done(result, not is_empty(value) and not bad, f"{spec['field']}={value!r} not in {spec.get('values')}")
    if kind == "equals":
        other = fields.get(spec["other"]) if "other" in spec else spec.get("value")
        label = spec.get("other", repr(spec.get("value")))
        return _done(result, _norm(value) == _norm(other), f"{spec['field']}={value!r} != {label}={other!r}")
    if kind == "min_words":
        words = len(str(value or "").split())
        minimum = int(spec.get("min", 1))
        return _done(result, words >= minimum, f"{spec['field']} has {words} words (< {minimum})")
    if kind == "not_contains":
        text = _norm(value)
        found = [v for v in spec.get("values") or [] if _norm(v) in text]
        return _done(result, not found, f"{spec['field']} contains {found}")
    if kind == "range":
        low, high = float(spec.get("min", 0)), float(spec.get("max", 1))
        bad = {f: fields.get(f) for f in spec.get("fields") or [spec.get("field")]
               if not isinstance(fields.get(f), (int, float)) or not low <= fields.get(f) <= high}
        return _done(result, not bad, f"not numbers in [{low}, {high}]: {bad}")
    if kind == "same_count":
        counts = {f: len(_items(fields.get(f))) for f in spec.get("fields") or []}
        return _done(result, len(set(counts.values())) <= 1, f"counts differ: {counts}")
    # subset
    allowed = [x for f in _items(spec.get("of")) for x in _items(fields.get(f))]
    extra = [v for v in _items(value) if v not in allowed]
    return _done(result, not extra, f"{spec['field']} has {extra} not in {spec.get('of')}")


def _when(condition: dict[str, Any] | None, fields: dict[str, Any]) -> str:
    """'' when the check should run, else the reason it is skipped."""
    if not condition:
        return ""
    value = fields.get(condition.get("field", ""))
    if "in" in condition:
        allowed = _items(condition["in"])
        holds = any(v in allowed for v in _items(value))
    elif "is" in condition:
        holds = any(v == condition["is"] for v in (value if isinstance(value, list) else [value]))
    else:
        holds = (not is_empty(value)) == bool(condition.get("present", True))
    rule = ", ".join(f"{k} {v}" for k, v in condition.items() if k != "field")
    return "" if holds else f"skipped: runs only when {condition.get('field')} {rule}"


def _pair(spec: dict[str, Any], expected: dict[str, Any]) -> tuple[str, list[str]] | None:
    """(field name, expected items) of the first compare pair the case has an expected value for."""
    pairs = spec.get("compare") or [{"field": spec.get("field"), "expected": spec.get("expected")}]
    for pair in pairs:
        want = _items(expected.get(pair.get("expected", "")))
        if want:
            return pair["field"], want
    return None


def _expected_names(spec: dict[str, Any]) -> str:
    pairs = spec.get("compare") or [{"expected": spec.get("expected")}]
    return " or ".join(f"expected.{p.get('expected')}" for p in pairs)


def _items(value: Any) -> list[str]:
    """Anything -> a list of normalised texts (so ids and titles compare cleanly)."""
    if is_empty(value):
        return []
    return [_norm(v) for v in (value if isinstance(value, list) else [value]) if not is_empty(v)]


def _norm(value: Any) -> str:
    return " ".join(str(value if value is not None else "").casefold().split())


def _done(result: Result, passed: bool, reason_if_failed: str) -> Result:
    result.status = PASS if passed else FAIL
    result.reason = "" if passed else reason_if_failed
    return result
