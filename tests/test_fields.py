"""fields.yaml (trace fields), JMESPath-style paths, YAML checks, and `make fields`."""

import json

import pytest
from conftest import ROOT

from src import cli
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP
from src.fields import checks, extract
from src.fields.path import get
from src.runners.suite_runner import run_suite

TRACES = ROOT / "outputs/traces/knowledge_agent/sanity"


def trace(case_id):
    return json.loads((TRACES / f"{case_id}.json").read_text())


# --- paths ------------------------------------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("a.b", 1),
    ("a.missing.x", None),
    ("items[0].id", "x"),
    ("items[-1].id", "y"),
    ("items[5]", None),
    ("items[].id", ["x", "y"]),
    ("items[*].id", ["x", "y"]),
    ("groups.*.ids", [["1", "2"], ["3"]]),
    ("groups.*.ids[]", ["1", "2", "3"]),
    ("pairs[*][1]", ["p", "q"]),
    ("pairs[]", ["1", "p", "2", "q"]),                 # [] flattens one level, like JMESPath
    ("groups.*.pairs[][1]", ["p", "q"]),
])
def test_paths_behave_like_jmespath(path, expected):
    data = {"a": {"b": 1}, "items": [{"id": "x"}, {"id": "y"}], "pairs": [["1", "p"], ["2", "q"]],
            "groups": {"u1": {"ids": ["1", "2"], "pairs": [["1", "p"]]}, "u2": {"ids": ["3"], "pairs": [["2", "q"]]}}}
    assert get(data, path) == expected
    assert get(data, "") == data


def test_bad_path_is_a_config_error():
    with pytest.raises(ConfigError, match="Invalid path"):
        get({}, "a.]b")


# --- fields on the real Knowledge Agent traces -------------------------------------------------

def test_knowledge_agent_fields_from_the_full_metadata_path():
    values, missing = extract.extract(trace("TC_002"), load_agent("knowledge_agent").fields)
    assert missing == []
    assert values["answer"].startswith("To add a Support Need in Multi-Channel Processes (MCP)")
    assert values["rewritten_query"] == "add support need process"
    assert values["search_candidates"] == ["40346", "40345", "40011"]
    assert values["anchor_page_ids"] == ["40345"]
    assert values["anchor_titles"] == ["How To Add a Support Need in MCP"]             # where + pick
    assert values["expanded_page_ids"] == ["40017", "40015"]
    assert values["expansion_labels"] == ["reference", "exception_to"]                 # pairs[][1]
    assert values["cited_page_ids"] == ["40345", "40015"]
    assert values["caveats"] == [] and values["disclosures"] == []                     # present but empty
    assert values["metadata_missing"] == [False] and values["anchor_fallback"] is False
    assert values["evidence_content_length"] == 8535                                   # from a status message
    assert values["output_guardrail"] == "disabled"
    assert values["synthesizer_page_ids"] == ["40345", "40015"]                        # from the model reply
    assert values["stage_seconds"]["search_node"] == 5.0


def test_knowledge_agent_fields_from_the_fallback_path():
    values, _ = extract.extract(trace("TC_012"), load_agent("knowledge_agent").fields)
    assert values["branch_count"] == 2
    assert values["rewritten_query"] == "third party verification process\ncustomer absent third party support protocol"
    assert values["metadata_missing"] == [True, True]
    assert values["anchor_fallback"] is True and values["expansion_skipped"] is True
    assert values["anchor_page_ids"] == ["40022", "40015"]
    assert values["expanded_page_ids"] == []                                          # present, but empty


def test_field_options():
    data = {"raw_events": [
        {"actions": {"stateDelta": {"ids": ["1", "2", "2"], "old": "o"}}},
        {"actions": {"stateDelta": {"ids": ["1", "2", "2", "3"]}}},                      # latest state wins
        {"nodeInfo": {"path": "wf@1/worker@1"}, "output": {"x": "a"}},
        {"nodeInfo": {"path": "wf@1/worker@2"}, "output": {"x": "b"}},
        {"author": "judge_agent", "content": {"role": "model", "parts": [{"text": "```json\n{\"s\": 0.5}\n```"}]}},
        {"content": {"role": "user", "parts": [{"text": "Done. total=7 ok=yes"}]}},
    ], "latency_ms": 12.5}
    fields = extract.validate({
        "ids": {"from": "state", "path": "ids", "unique": True},
        "count": {"from": "state", "path": "ids", "count": True},
        "first_id": {"from": "state", "path": "ids", "first": True},
        "text": {"from": "state", "path": "ids", "join": ","},
        "renamed": {"from": "state", "path": ["new_name", "old"]},                     # first path that finds it
        "workers": {"from": "node", "node": "worker", "path": "x"},
        "score": {"from": "model", "agent": "judge_agent", "path": "s", "first": True},
        "total": {"from": "message", "contains": "Done.", "regex": r"total=(\d+)"},
        "latency": {"from": "trace", "path": "latency_ms"},
        "absent": {"from": "state", "path": "nope", "default": "n/a"},
    }, "test")
    values, missing = extract.extract(data, fields)
    assert values == {"ids": ["1", "2", "3"], "count": 4, "first_id": "1", "text": "1,2,2,3", "renamed": "o",
                      "workers": ["a", "b"], "score": 0.5, "total": 7, "latency": 12.5, "absent": "n/a"}
    assert missing == []
    required = extract.validate({"answer": {"from": "final", "path": "a", "required": True}}, "t")
    _, missing = extract.extract({}, required)
    assert missing == ["answer"]


@pytest.mark.parametrize("spec, message", [
    ({"from": "stat", "path": "a"}, "needs from:"),
    ({"from": "state", "pth": "a"}, "unknown keys"),
    ({"from": "node", "path": "a"}, "needs node:"),
    ({"from": "state", "path": "a", "where": {"id": "later"}}, "define 'later' above"),
])
def test_field_typos_fail_when_the_agent_loads(spec, message):
    with pytest.raises(ConfigError, match=message):
        extract.validate({"f": spec}, "fields.yaml")


# --- checks -----------------------------------------------------------------------------------

def run(spec, fields, expected=None):
    return checks.run_checks(checks.validate({"c": spec}, "t"), fields, {"expected": expected or {}})[0]


def test_check_types():
    fields = {"answer": "Raise a ticket with the service desk today", "confidence": "HIGH", "ids": ["1", "2"],
              "used": ["1", "2", "3"], "score": 0.4, "flags": [False, True], "caveats": []}
    assert run({"type": "present", "field": "answer"}, fields).status == PASS
    assert run({"type": "present", "field": "caveats"}, fields).status == FAIL
    assert run({"type": "one_of", "field": "confidence", "values": ["HIGH", "LOW"]}, fields).status == PASS
    assert run({"type": "equals", "field": "confidence", "value": "high"}, fields).status == PASS   # case-insensitive
    assert run({"type": "min_words", "field": "answer", "min": 10}, fields).status == FAIL
    assert run({"type": "not_contains", "field": "answer", "values": ["page_ids"]}, fields).status == PASS
    assert run({"type": "range", "fields": ["score"], "min": 0, "max": 1}, fields).status == PASS
    assert run({"type": "same_count", "fields": ["ids", "used"]}, fields).status == FAIL
    assert run({"type": "subset", "field": "ids", "of": ["used"]}, fields).status == PASS
    assert run({"type": "present", "field": "caveats", "when": {"field": "flags", "is": True}}, fields).status == FAIL
    skipped = run({"type": "present", "field": "caveats", "when": {"field": "confidence", "in": ["LOW"]}}, fields)
    assert skipped.status == SKIP and "runs only when confidence" in skipped.reason


def test_comparing_checks_use_the_first_label_the_case_has():
    fields = {"anchor_ids": ["40345"], "anchor_titles": ["How To Add a Support Need in MCP"],
              "expanded": ["a", "b", "c", "d"]}
    anchor_hit = {"type": "any_in", "compare": [{"field": "anchor_ids", "expected": "ids"},
                                                {"field": "anchor_titles", "expected": "titles"}]}
    assert run(anchor_hit, fields, {"titles": ["How to Add a support need in MCP"]}).status == PASS
    assert run(anchor_hit, fields, {"ids": ["40346"]}).status == FAIL
    missing = run(anchor_hit, fields, {})
    assert missing.status == SKIP and "expected.ids or expected.titles" in missing.reason

    precision = run({"type": "precision", "field": "expanded", "expected": "rel", "threshold": 0.7},
                    fields, {"rel": ["a", "b"]})
    assert (precision.status, precision.score) == (FAIL, 0.5)
    recall = run({"type": "recall", "field": "expanded", "expected": "rel"}, fields, {"rel": ["a", "b"]})
    assert (recall.status, recall.score) == (PASS, 1.0)
    nothing = run({"type": "precision", "field": "none", "expected": "rel"}, fields, {"rel": ["a"]})
    assert nothing.status == SKIP                                                      # nothing expanded


def test_check_typos_fail_when_the_agent_loads():
    with pytest.raises(ConfigError, match="needs type"):
        checks.validate({"c": {"type": "is_there", "field": "a"}}, "agent.yaml")
    with pytest.raises(ConfigError, match="needs field: \\+ expected:"):
        checks.validate({"c": {"type": "any_in", "field": "a"}}, "agent.yaml")


# --- make fields ------------------------------------------------------------------------------

def test_make_fields_previews_fields_and_checks(capsys):
    assert cli.main(["fields", "knowledge_agent", "--case", "TC_012"]) == 0
    out = capsys.readouterr().out
    assert "=== TC_012.json" in out
    assert "empty     disclosures" in out and "empty     expanded_page_ids" in out
    assert "empty     expansion_labels" in out                                           # branches, none expanded
    assert "FAIL      fallback_disclosed" in out
    with pytest.raises(ConfigError, match="No saved trace"):
        cli.main(["fields", "knowledge_agent", "--case", "TC_999"])


# --- evidence text from Athena (from: athena) ----------------------------------------------------

def test_evidence_text_is_fetched_once_and_saved(outputs, monkeypatch):
    from conftest import fake_athena_page

    from src.fields import evidence
    calls = []
    monkeypatch.setattr(evidence, "fetch_page", lambda pid: calls.append(pid) or fake_athena_page(pid))
    for name in ("40345", "40017", "40015"):
        (outputs / f"outputs/evidence/athena/{name}.json").unlink()               # start with no saved copies
    fields = load_agent("knowledge_agent").fields

    values, _ = extract.extract(trace("TC_002"), fields)                           # live run: fetch
    assert values["contexts"] == ["How To Add a Support Need in MCP\n\nText of page 40345.",
                                  "How to Add a Support Need\n\nText of page 40017.",
                                  "Consent Needed for Adding Support Needs\n\nText of page 40015."]
    assert sorted(calls) == ["40015", "40017", "40345"]
    assert (outputs / "outputs/evidence/athena/40345.json").is_file()              # saved for OFFLINE runs

    extract.extract(trace("TC_012"), fields)                                       # 40015 again: not refetched
    assert sorted(calls) == ["40015", "40017", "40022", "40345"]

    evidence.clear_cache()
    calls.clear()
    values, _ = extract.extract(trace("TC_002"), fields, offline=True)             # OFFLINE: saved copies only
    assert len(values["contexts"]) == 3 and calls == []


def _fake_judges(monkeypatch, seen=None):
    from src.metrics import judges

    def fake_score(name, metric, values, threshold):
        if seen is not None:
            seen[name] = values
        return 0.9, ""

    monkeypatch.setattr(judges, "score_with_deepeval", fake_score)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)


def test_missing_evidence_is_an_error_not_a_low_score(outputs, monkeypatch):
    _fake_judges(monkeypatch)
    (outputs / "outputs/evidence/athena/40017.json").unlink()
    case = run_suite("knowledge_agent", "sanity", offline=True, case_ids=["TC_002"]).cases[0]
    error = next(r for r in case.results if r.name == "evidence_fetch")
    assert error.status == "error" and "page 40017" in error.reason and "OFFLINE" in error.reason
    assert "faithfulness need" in error.reason                     # says which judge wanted the evidence
    assert case.status == "error"


def test_evidence_is_fetched_only_when_a_judge_needs_it(outputs, monkeypatch):
    """A relevance-only suite never calls Athena — so Athena being down can't ERROR it."""
    _fake_judges(monkeypatch)
    from src.fields import evidence
    evidence.clear_cache()
    for saved in (outputs / "outputs/evidence/athena").glob("*.json"):
        saved.unlink()                                             # no saved pages at all
    monkeypatch.setattr(evidence, "fetch_page", lambda pid: pytest.fail("Athena was called"))
    traces = outputs / "outputs/traces/knowledge_agent"
    (traces / "relevance_only").mkdir()
    (traces / "relevance_only" / "TC_002.json").write_text((traces / "sanity" / "TC_002.json").read_text())
    case = run_suite("knowledge_agent", "relevance_only", offline=True, case_ids=["TC_002"]).cases[0]
    assert [r.name for r in case.results] == ["relevance"]         # checks: none -> judges only
    assert case.status == "pass" and not case.details["contexts"]


def test_faithfulness_judge_gets_the_evidence_text(outputs, monkeypatch):
    seen = {}
    _fake_judges(monkeypatch, seen)
    case = run_suite("knowledge_agent", "sanity", offline=True, case_ids=["TC_002"]).cases[0]
    faithfulness = next(r for r in case.results if r.name == "faithfulness")
    assert faithfulness.status == "pass"
    assert seen["faithfulness"]["contexts"][0].startswith("How To Add a Support Need in MCP")
    assert seen["faithfulness"]["answer"].startswith("To add a Support Need in Multi-Channel Processes")


def test_checks_in_groups_and_suites_that_pick_them(temp_agents):
    folder = temp_agents / "demo"
    folder.mkdir()
    (folder / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\n"
        "metrics: {relevance: {threshold: 0.7}}\n"
        "checks:\n"
        "  answer:\n"
        "    long_enough: {type: min_words, field: answer, min: 3}\n"
        "    no_markers:  {type: not_contains, field: answer, values: [page_ids]}\n"
        "  loose_check:   {type: present, field: answer}\n"
        "suites:\n"
        "  everything: {metrics: [relevance]}\n"
        "  judges_only: {metrics: [relevance], checks: none}\n"
        "  picked: {metrics: [relevance], checks: [answer, basic]}\n"
    )
    agent = load_agent("demo")
    assert agent.checks["long_enough"]["group"] == "answer" and "group" not in agent.checks["loose_check"]
    assert len(agent.checks_for(agent.suite("everything"))) == 3
    assert agent.checks_for(agent.suite("judges_only")) == {}
    assert sorted(agent.checks_for(agent.suite("picked"))) == ["long_enough", "no_markers"]

    (folder / "agent.yaml").write_text((folder / "agent.yaml").read_text().replace("[answer, basic]", "[answr]"))
    with pytest.raises(ConfigError, match="neither checks nor groups"):
        load_agent("demo")


def test_athena_field_needs_ids_defined_above():
    with pytest.raises(ConfigError, match="needs ids:"):
        extract.validate({"contexts": {"from": "athena", "ids": "page_ids"}}, "fields.yaml")
