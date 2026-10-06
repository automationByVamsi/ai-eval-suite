"""
Deterministic checks written in YAML (agents/<agent>/checks.yaml), run on the fields
from fields.yaml. Each produces one pass / fail / skip result, like a parser.py check.

    checks:
      confidence_valid:   {type: one_of, field: confidence, values: [HIGH, MEDIUM, LOW]}
      anchor_hit:         {type: any_in, field: anchor_page_ids, expected: expected_anchor_page_ids}
      fallback_disclosed: {type: present, field: disclosures, when: {field: metadata_missing, is: true}}

Types:
  present       the field has a value (not empty); with fields: [...], every one of them
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

`k: 5` on a comparing check counts only the first 5 items of the field (precision@k / recall@k on
a ranked list, e.g. the agent's search candidates). `expected:` may list several keys; their values
are combined, e.g. expected: [expected_anchor_page_ids, expected_related_page_ids].

`when:` runs the check only if a condition holds, else SKIP:
      when: {field: confidence, in: [MEDIUM, LOW]}     the value is one of these
      when: {field: metadata_missing, is: true}         the value (or any item of a list) is true
      when: {field: cited_page_ids, present: true}      the field has a value
      when: {expected: should_decline, is: true}        a value in the test case's expected block
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP, Result
from src.fields.extract import is_empty

KEYS = {"type", "field", "fields", "expected", "compare", "values", "value", "other", "of", "min", "max",
        "threshold", "when", "description", "group", "k"}


# --- loading: check the YAML once, when the agent loads ------------------------------------------

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
    """A group is a mapping of checks (no `type:` of its own)."""
    return (isinstance(spec, dict) and "type" not in spec and bool(spec)
            and all(isinstance(v, dict) for v in spec.values()))


def _add(flat: dict[str, dict[str, Any]], name: str, spec: Any, where: str) -> None:
    """Validate one check and add it to `flat`."""
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


# --- running: one Result per check ---------------------------------------------------------------

@dataclass
class Outcome:
    """What one check decided. passed=None means skipped."""

    passed: bool | None
    reason: str = ""                 # why it failed or was skipped ("" when it passed)
    score: float | None = None       # precision / recall only
    threshold: float | None = None


def _verdict(passed: bool, reason_if_failed: str) -> Outcome:
    return Outcome(passed, "" if passed else reason_if_failed)


def _skipped(reason: str) -> Outcome:
    return Outcome(None, f"skipped: {reason}")


def run_checks(checks: dict[str, dict[str, Any]], fields: dict[str, Any], case: dict[str, Any]) -> list[Result]:
    """One Result per check, in the order they are written."""
    expected = case.get("expected") or {}
    return [_one(name, spec, fields, expected) for name, spec in checks.items()]


def _one(name: str, spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any]) -> Result:
    """Run one check: its `when:` condition first, then the rule for its type."""
    skip_reason = _when(spec.get("when"), fields, expected)
    if skip_reason:
        outcome = Outcome(None, skip_reason)
    elif spec["type"] in COMPARING:
        outcome = _compare(spec, fields, expected)
    else:
        outcome = RULES[spec["type"]](spec, fields)
    return _result(name, spec, outcome)


def _result(name: str, spec: dict[str, Any], outcome: Outcome) -> Result:
    status = SKIP if outcome.passed is None else PASS if outcome.passed else FAIL
    return Result(name=name, kind="check", status=status, reason=outcome.reason,
                  score=outcome.score, threshold=outcome.threshold, group=spec.get("group", ""))


# --- the rules that read fields only: (spec, fields) -> Outcome ----------------------------------

def _value(spec: dict[str, Any], fields: dict[str, Any]) -> Any:
    """The value of the check's `field:`."""
    return fields.get(spec.get("field", ""))


def _present(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    names = spec.get("fields") or [spec.get("field")]          # several fields: every one must have a value
    empty = [n for n in names if is_empty(fields.get(n))]
    return _verdict(not empty, f"{', '.join(empty)} empty")


def _one_of(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    value = _value(spec, fields)
    allowed = _items(spec.get("values"))
    bad = [v for v in _items(value) if v not in allowed]
    return _verdict(not is_empty(value) and not bad, f"{spec['field']}={value!r} not in {spec.get('values')}")


def _equals(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    value = _value(spec, fields)
    other = fields.get(spec["other"]) if "other" in spec else spec.get("value")
    label = spec.get("other", repr(spec.get("value")))
    return _verdict(_norm(value) == _norm(other), f"{spec['field']}={value!r} != {label}={other!r}")


def _min_words(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    words = len(str(_value(spec, fields) or "").split())
    minimum = int(spec.get("min", 1))
    return _verdict(words >= minimum, f"{spec['field']} has {words} words (< {minimum})")


def _not_contains(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    text = _norm(_value(spec, fields))
    found = [v for v in spec.get("values") or [] if _norm(v) in text]
    return _verdict(not found, f"{spec['field']} contains {found}")


def _range(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    low, high = float(spec.get("min", 0)), float(spec.get("max", 1))

    def in_range(value: Any) -> bool:
        return isinstance(value, (int, float)) and low <= value <= high

    names = spec.get("fields") or [spec.get("field")]
    bad = {name: fields.get(name) for name in names if not in_range(fields.get(name))}
    return _verdict(not bad, f"not numbers in [{low}, {high}]: {bad}")


def _same_count(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    counts = {name: len(_items(fields.get(name))) for name in spec.get("fields") or []}
    return _verdict(len(set(counts.values())) <= 1, f"counts differ: {counts}")


def _subset(spec: dict[str, Any], fields: dict[str, Any]) -> Outcome:
    allowed = [item for name in _items(spec.get("of")) for item in _items(fields.get(name))]
    extra = [v for v in _items(_value(spec, fields)) if v not in allowed]
    return _verdict(not extra, f"{spec['field']} has {extra} not in {spec.get('of')}")


RULES: dict[str, Callable[[dict[str, Any], dict[str, Any]], Outcome]] = {
    "present": _present,
    "one_of": _one_of,
    "equals": _equals,
    "min_words": _min_words,
    "not_contains": _not_contains,
    "range": _range,
    "same_count": _same_count,
    "subset": _subset,
}


# --- the rules that compare a field with the case's expected values -----------------------------
# Each gets (spec, field name, the field's items, the expected items) -> Outcome.

def _compare(spec: dict[str, Any], fields: dict[str, Any], expected: dict[str, Any]) -> Outcome:
    """Find what to compare (first `compare:` pair the case has), then apply the comparison."""
    pair = _pair(spec, expected)
    if pair is None:
        return _skipped(f"case has no {_expected_names(spec)}")
    field_name, want = pair
    have = _items(fields.get(field_name))
    if spec.get("k"):                       # only the first k items count (ranked lists: precision@k ...)
        have = have[: int(spec["k"])]
    return COMPARISONS[spec["type"]](spec, field_name, have, want)


def _any_in(spec: dict[str, Any], field_name: str, have: list[str], want: list[str]) -> Outcome:
    return _verdict(any(w in have for w in want), f"none of {sorted(want)} in {field_name}={sorted(have)}")


def _all_in(spec: dict[str, Any], field_name: str, have: list[str], want: list[str]) -> Outcome:
    missing = [w for w in want if w not in have]
    return _verdict(not missing, f"{field_name} lacks {missing}")


def _precision(spec: dict[str, Any], field_name: str, have: list[str], want: list[str]) -> Outcome:
    return _ratio(spec, field_name, have, want, base=have)        # share of what was found that was expected


def _recall(spec: dict[str, Any], field_name: str, have: list[str], want: list[str]) -> Outcome:
    return _ratio(spec, field_name, have, want, base=want)        # share of what was expected that was found


def _ratio(spec: dict[str, Any], field_name: str, have: list[str], want: list[str], base: list[str]) -> Outcome:
    """|have ∩ want| / |base|, passed when >= threshold. Skipped when base is empty (nothing to divide by)."""
    if not base:
        return _skipped(f"{field_name} is empty")
    common = {w for w in want if w in have}
    threshold = float(spec.get("threshold", 0.7))
    score = round(len(common) / len(set(base)), 4)
    passed = score >= threshold
    reason = f"{spec['type']} {score:.2f} < {threshold}: {field_name}={sorted(have)} expected={sorted(want)}"
    return Outcome(passed, "" if passed else reason, score=score, threshold=threshold)


COMPARISONS: dict[str, Callable[[dict[str, Any], str, list[str], list[str]], Outcome]] = {
    "any_in": _any_in,
    "all_in": _all_in,
    "precision": _precision,
    "recall": _recall,
}

COMPARING = set(COMPARISONS)
TYPES = set(RULES) | COMPARING


def _pair(spec: dict[str, Any], expected: dict[str, Any]) -> tuple[str, list[str]] | None:
    """(field name, expected items) of the first compare pair the case has an expected value for."""
    pairs = spec.get("compare") or [{"field": spec.get("field"), "expected": spec.get("expected")}]
    for pair in pairs:
        want = _expected_items(expected, pair.get("expected", ""))
        if want:
            return pair["field"], want
    return None


def _expected_items(expected: dict[str, Any], keys: str | list[str]) -> list[str]:
    """The case's expected items for one key, or for several keys together (repeats dropped)."""
    keys = keys if isinstance(keys, list) else [keys]
    return list(dict.fromkeys(item for key in keys for item in _items(expected.get(key))))


def _expected_names(spec: dict[str, Any]) -> str:
    """'expected.a or expected.b+expected.c' — for the skip reason."""
    pairs = spec.get("compare") or [{"expected": spec.get("expected")}]
    names = [p.get("expected") for p in pairs]
    return " or ".join("+".join(f"expected.{k}" for k in (n if isinstance(n, list) else [n])) for n in names)


# --- when: ----------------------------------------------------------------------------------------

def _when(condition: dict[str, Any] | None, fields: dict[str, Any], expected: dict[str, Any] | None = None) -> str:
    """
    '' when the check should run, else the reason it is skipped. The condition reads a field, or
    with `expected:` a key of the test case's expected block, e.g. {expected: should_decline, is: true}.
    """
    if not condition:
        return ""
    if "expected" in condition:
        value = (expected or {}).get(condition["expected"])
        label = condition.get("field", f"expected.{condition['expected']}")
    else:
        value = fields.get(condition.get("field", ""))
        label = condition.get("field")
    if _holds(condition, value):
        return ""
    rule = ", ".join(f"{k} {v}" for k, v in condition.items() if k not in ("field", "expected"))
    return f"skipped: runs only when {label} {rule}"


def _holds(condition: dict[str, Any], value: Any) -> bool:
    """Does `value` meet the condition's rule (in: / is: / present:)?"""
    match condition:
        case {"in": allowed}:
            return any(v in _items(allowed) for v in _items(value))
        case {"is": wanted}:
            return any(v == wanted for v in (value if isinstance(value, list) else [value]))
        case _:
            return (not is_empty(value)) == bool(condition.get("present", True))


# --- helpers ----------------------------------------------------------------------------------------

def _items(value: Any) -> list[str]:
    """Anything -> a list of normalised texts (so ids and titles compare cleanly)."""
    if is_empty(value):
        return []
    return [_norm(v) for v in (value if isinstance(value, list) else [value]) if not is_empty(v)]


def _norm(value: Any) -> str:
    """Lower case, single spaces: "How To  Add" -> "how to add"."""
    return " ".join(str(value if value is not None else "").casefold().split())
