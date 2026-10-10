"""fields.yaml (trace fields as JMESPath queries), YAML checks, and `make fields`."""

import json

import pytest
from conftest import ROOT

from src import cli
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.core.results import FAIL, PASS, SKIP
from src.fields import checks, extract
from src.runners.suite_runner import run_suite

TRACES = ROOT / "outputs/traces/knowledge_agent/sanity"


def trace(case_id):
    return json.loads((TRACES / f"{case_id}.json").read_text())


# --- the trace as one document -------------------------------------------------------------

def test_the_trace_becomes_one_document():
    data = {"raw_events": [
        {"actions": {"stateDelta": {"ids": ["1", "2"], "old": "o"}}},
        {"actions": {"stateDelta": {"ids": ["1", "2", "2", "3"]}}},                      # latest state wins
        {"nodeInfo": {"path": "wf@1/worker@1"}, "output": {"x": "a"}, "timestamp": 10},
        {"nodeInfo": {"path": "wf@1/worker@2"}, "output": {"x": "b"}, "timestamp": 12},
        {"author": "judge_agent", "content": {"role": "model", "parts": [{"text": "```json\n{\"s\": 0.5}\n```"}]}},
        {"content": {"role": "user", "parts": [{"text": "Done. total=7"}]}},
        {"nodeInfo": {"path": "wf@1", "outputFor": ["wf"]}, "output": {"answer": "hi"}},
    ], "latency_ms": 12.5}
    document = extract.view(data)
    assert document["final"] == {"answer": "hi"}
    assert document["state"] == {"ids": ["1", "2", "2", "3"], "old": "o"}
    assert document["nodes"]["worker"] == [{"x": "a"}, {"x": "b"}]
    assert document["models"] == {"judge_agent": [{"s": 0.5}]}                       # JSON reply parsed
    assert document["messages"][-1] == "Done. total=7"
    assert document["timing"] == {"worker": 2}
    assert document["trace"]["latency_ms"] == 12.5


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
    assert values["metadata_missing"] == [False] and values["anchor_fallback"] == []
    assert values["validation_message"].endswith("content_length=8535")               # a status message
    assert values["synthesizer_page_ids"] == ["40345", "40015"]                        # from the model reply
    assert values["stage_seconds"]["search_node"] == 5.0


def test_knowledge_agent_fields_from_the_fallback_path():
    values, _ = extract.extract(trace("TC_012"), load_agent("knowledge_agent").fields)
    assert values["branch_count"] == 2
    assert values["rewritten_query"] == "third party verification process\ncustomer absent third party support protocol"
    assert values["metadata_missing"] == [True, True]
    assert values["anchor_fallback"] and values["expansion_skipped"]                  # the agent's reasons
    assert values["anchor_page_ids"] == ["40022", "40015"]
    assert values["expanded_page_ids"] == []                                          # present, but empty


def test_field_options():
    data = {"raw_events": [{"actions": {"stateDelta": {
        "ids": ["1", "2", "2", "3"], "old": "o", "items": [{"id": "1", "t": "A"}, {"id": "3", "t": "C"}]}}}]}
    fields = extract.validate({
        "ids": {"path": "state.ids", "unique": True},
        "count": "length(state.ids)",                                                 # plain JMESPath
        "text": {"path": "state.ids", "join": ","},
        "renamed": {"path": ["state.new_name", "state.old"]},                          # first path that finds it
        "picked": {"path": "state.items", "where": {"id": "ids"}, "pick": "t"},
        "absent": {"path": "state.nope", "default": "n/a"},
    }, "test")
    values, missing = extract.extract(data, fields)
    assert values == {"ids": ["1", "2", "3"], "count": 4, "text": "1,2,2,3", "renamed": "o",
                      "picked": ["A", "C"], "absent": "n/a"}
    assert missing == []
    _, missing = extract.extract({}, extract.validate({"answer": {"path": "final.a", "required": True}}, "t"))
    assert missing == ["answer"]


@pytest.mark.parametrize("spec, message", [
    ({"from": "state", "path": "a"}, "old {from: x, path: y} form"),
    ({"pth": "state.a"}, "unknown keys"),
    ({"join": ","}, "needs path:"),
    ("state.]a", "invalid path"),
    ({"path": "state.a", "where": {"id": "later"}}, "define them above it"),
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
    assert "PASS      citations_in_evidence_set" in out and "SKIP      anchor_hit" in out   # no golden data
    with pytest.raises(ConfigError, match="No saved trace"):
        cli.main(["fields", "knowledge_agent", "--case", "TC_999"])


# --- values looked up outside the trace (lookup:, agents/<agent>/lookups.py) -----------------------

SAVED = "outputs/lookups/knowledge_agent/get_page_content_from_athena"


def _counting(calls):
    from conftest import fake_athena_page
    return lambda pid: calls.append(pid) or fake_athena_page(pid)


def test_evidence_text_is_looked_up_once_and_saved(outputs, monkeypatch):
    from conftest import use_lookup

    from src.fields import lookup
    calls = []
    use_lookup(monkeypatch, _counting(calls))
    for name in ("40345", "40017", "40015"):
        (outputs / SAVED / f"{name}.json").unlink()                              # start with no saved copies
    fields = load_agent("knowledge_agent").fields

    values, _ = extract.extract(trace("TC_002"), fields)                           # live run: look up
    assert values["contexts"] == ["How To Add a Support Need in MCP\n\nText of page 40345.",
                                  "How to Add a Support Need\n\nText of page 40017.",
                                  "Consent Needed for Adding Support Needs\n\nText of page 40015."]
    assert values["anchor_page_content"] == "How To Add a Support Need in MCP\n\nText of page 40345."
    assert sorted(calls) == ["40015", "40017", "40345"]                          # 40345 twice: looked up once
    assert (outputs / SAVED / "40345.json").is_file()                            # saved for OFFLINE runs

    extract.extract(trace("TC_012"), fields)                                       # 40015 again: not again
    assert sorted(calls) == ["40015", "40017", "40022", "40345"]

    lookup.clear_cache()
    calls.clear()
    values, _ = extract.extract(trace("TC_002"), fields, offline=True)             # OFFLINE: saved copies
    assert len(values["contexts"]) == 3 and calls == []


def _fake_judges(monkeypatch, seen=None):
    from src.metrics import judges

    def fake_score(name, metric, values, threshold):
        if seen is not None:
            seen[name] = values
        return 0.9, ""

    monkeypatch.setattr(judges, "score_with_deepeval", fake_score)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)


def test_a_failed_lookup_is_an_error_not_a_low_score(outputs, monkeypatch):
    from conftest import use_lookup
    _fake_judges(monkeypatch)
    (outputs / SAVED / "40017.json").unlink()

    def athena_down(page_id):
        raise ConnectionError("Athena unreachable")

    use_lookup(monkeypatch, athena_down)
    case = run_suite("knowledge_agent", "sanity", offline=True, case_ids=["TC_002"]).cases[0]
    error = next(r for r in case.results if r.name == "lookup")
    assert error.status == "error" and "get_page_content_from_athena(40017)" in error.reason
    assert "Athena unreachable" in error.reason and "lookups.py" in error.reason
    assert "faithfulness and hallucination could not run" in error.reason                 # says which judge wanted it
    assert case.status == "error"


def test_offline_run_looks_up_ids_it_never_saved(outputs, monkeypatch):
    """OFFLINE=1 replays the agent's trace; ids never saved are still looked up once, then reused."""
    from conftest import use_lookup

    from src.fields import lookup
    _fake_judges(monkeypatch)
    for saved in (outputs / SAVED).glob("*.json"):
        saved.unlink()
    calls = []
    use_lookup(monkeypatch, _counting(calls))
    case = run_suite("knowledge_agent", "sanity", offline=True, case_ids=["TC_002"]).cases[0]
    assert next(r for r in case.results if r.name == "faithfulness").status == "pass"
    assert sorted(calls) == ["40015", "40017", "40345"]
    assert (outputs / SAVED / "40345.json").is_file()

    lookup.clear_cache()
    calls.clear()
    run_suite("knowledge_agent", "sanity", offline=True, case_ids=["TC_002"])
    assert calls == []                                                   # second replay: saved copies


def test_make_fields_never_calls_a_lookup(outputs, monkeypatch):
    from conftest import use_lookup

    from src.fields import lookup
    (outputs / SAVED / "40017.json").unlink()
    use_lookup(monkeypatch, lambda pid: pytest.fail("lookup was called"))
    folder = load_agent("knowledge_agent").folder
    _, problems = lookup.texts(folder, "get_page_content_from_athena", ["40345", "40017"], offline=True, local=True)
    assert problems and "no saved copy yet" in problems[0]


def test_lookups_run_only_when_a_judge_needs_them(outputs, monkeypatch):
    """A relevance-only suite never looks anything up — so Athena being down can't ERROR it."""
    from conftest import use_lookup
    _fake_judges(monkeypatch)
    for saved in (outputs / SAVED).glob("*.json"):
        saved.unlink()                                             # no saved pages at all
    use_lookup(monkeypatch, lambda pid: pytest.fail("lookup was called"))
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


def test_knowledge_agent_lookup_cleans_the_athena_html(monkeypatch):
    """lookups.py: Athena's page JSON (as in Bruno's "Get Page Content") -> title + plain text."""
    from src.fields import lookup
    folder = load_agent("knowledge_agent").folder
    module = lookup._module(folder)
    raw = {"@revision": "5", "@title": "Recording Support Needs",
           "body": ['<div class="mt-section"><h2 class="editable">Overview</h2><p>Colleagues in Messaging'
                    '&nbsp;should use this.</p><ul><li>Refer to your <a href="https://x">line manager</a>.</li>'
                    '</ul></div>', {"toc": "skipped"}]}
    monkeypatch.setattr(module, "athena_http", lambda timeout: __import__("contextlib").nullcontext(None))
    monkeypatch.setattr(module, "get_page_content", lambda http, page_id: raw)
    page = module.get_page_content_from_athena("40021")
    assert page["title"] == "Recording Support Needs" and page["revision"] == "5"
    assert "<" not in page["text"] and "&nbsp;" not in page["text"]
    assert "Colleagues in Messaging should use this." in page["text"]
    assert "- Refer to your line manager" in page["text"]


def test_lookup_values_can_be_any_json():
    """Another agent's lookup may return a record from its own API: it reaches the judge as JSON text."""
    from src.fields.lookup import as_text
    assert as_text("plain") == "plain"
    assert as_text({"title": "T", "text": "body"}) == "T\n\nbody"
    assert as_text({"case_id": "C1", "status": "open"}) == '{\n  "case_id": "C1",\n  "status": "open"\n}'


def test_lookup_mistakes_fail_when_the_agent_loads(temp_agents):
    folder = temp_agents / "demo"
    folder.mkdir()
    (folder / "agent.yaml").write_text("connection: {base_url: http://x, app_name: demo}\n"
                                       "suites: {sanity: {metrics: []}}\n")
    (folder / "fields.yaml").write_text("fields:\n  ids: final.ids\n"
                                        "  texts: {lookup: get_record, ids: ids}\n")
    with pytest.raises(ConfigError, match="lookups.py with a function get_record"):
        load_agent("demo")
    (folder / "lookups.py").write_text("def get_recrod(item):\n    return item\n")
    with pytest.raises(ConfigError, match="has no function 'get_record'"):
        load_agent("demo")


def test_checks_in_groups_and_suites_that_pick_them(temp_agents):
    folder = temp_agents / "demo"
    folder.mkdir()
    (folder / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\n"
        "metrics: {relevance: {threshold: 0.7}}\n"
        "suites:\n"
        "  everything: {metrics: [relevance]}\n"
        "  judges_only: {metrics: [relevance], checks: none}\n"
        "  picked: {metrics: [relevance], checks: [answer, basic]}\n"
    )
    (folder / "checks.yaml").write_text(
        "checks:\n"
        "  answer:\n"
        "    long_enough: {type: min_words, field: answer, min: 3}\n"
        "    no_markers:  {type: not_contains, field: answer, values: [page_ids]}\n"
        "  loose_check:   {type: present, field: answer}\n"
    )
    agent = load_agent("demo")
    assert agent.checks["long_enough"]["group"] == "answer" and "group" not in agent.checks["loose_check"]
    assert len(agent.checks_for(agent.suite("everything"))) == 3
    assert agent.checks_for(agent.suite("judges_only")) == {}
    assert sorted(agent.checks_for(agent.suite("picked"))) == ["long_enough", "no_markers"]

    (folder / "agent.yaml").write_text((folder / "agent.yaml").read_text().replace("[answer, basic]", "[answr]"))
    with pytest.raises(ConfigError, match="neither checks nor groups"):
        load_agent("demo")


def test_checks_live_only_in_checks_yaml(temp_agents):
    folder = temp_agents / "demo"
    folder.mkdir()
    agent_yaml = ("connection: {base_url: http://x, app_name: demo}\n"
                  "metrics: {relevance: {threshold: 0.7}}\n"
                  "suites: {everything: {metrics: [relevance]}}\n")
    (folder / "agent.yaml").write_text(agent_yaml)
    assert load_agent("demo").checks == {}                       # checks.yaml is optional

    (folder / "checks.yaml").write_text("checks:\n#  answer: ...   (all commented out)\n")
    assert load_agent("demo").checks == {}                       # the template's empty checks.yaml loads

    (folder / "checks.yaml").write_text("checks:\n  answr:\n    long_enough: {type: min_wrds, field: answer}\n")
    with pytest.raises(ConfigError, match="checks.yaml"):           # errors name the file the check is in
        load_agent("demo")

    (folder / "agent.yaml").write_text(agent_yaml + "checks:\n  extra: {type: present, field: answer}\n")
    with pytest.raises(ConfigError, match="belongs in .*checks.yaml"):   # one place only: never silently ignored
        load_agent("demo")


def test_lookup_field_needs_ids_defined_above():
    with pytest.raises(ConfigError, match="needs ids:"):
        extract.validate({"contexts": {"lookup": "f", "ids": "page_ids"}}, "fields.yaml")
