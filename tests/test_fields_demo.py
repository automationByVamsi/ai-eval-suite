"""
fields.yaml, demonstrated: what happens when a field is right, wrong, renamed, required or mistyped.

Every scenario below is a small fields.yaml written inline, run on a SAVED trace
(outputs/traces/knowledge_agent/sanity/TC_002.json): no agent call, no judges, no network.
The real agents/knowledge_agent/fields.yaml is never touched.

Run it and read the printout (-s shows the prints):

    uv run --frozen pytest tests/test_fields_demo.py -s -v

To try your own idea: copy a scenario, change the YAML, run again.
"""

import json

import pytest
import yaml
from conftest import ROOT

from src.core.exceptions import ConfigError
from src.fields.extract import extract, validate

TRACE = json.loads((ROOT / "outputs/traces/knowledge_agent/sanity/TC_002.json").read_text())


def run_fields(title: str, fields_yaml: str) -> tuple[dict, list]:
    """Read the YAML exactly like the framework does, extract every field, print the result."""
    fields = validate(yaml.safe_load(fields_yaml)["fields"], "demo fields.yaml")
    values, missing = extract(TRACE, fields, offline=True)
    print(f"\n--- {title} ---")
    for name, value in values.items():
        mark = ("MISSING" if name in missing else "NOT FOUND" if value is None
                else "empty" if value in ("", [], {}) else "ok")
        print(f"  {mark:<9} {name:<22} = {json.dumps(value)[:90]}")
    return values, missing


def test_1_correct_paths():
    """The happy path: each line says where to look (from) and what to take (path)."""
    values, missing = run_fields("1. correct paths", """
fields:
  answer:          {from: final, path: answer.summary}
  confidence:      {from: final, path: confidence}
  anchor_page_ids: {from: state, path: evidence_set.anchor_page_ids}
  evidence_titles: {from: final, path: "evidence[].title"}
  branch_count:    {from: state, path: "search_branches.*.sub_query", count: true}
""")
    assert values["answer"].startswith("To add a Support Need")
    assert values["confidence"] == "HIGH"
    assert values["anchor_page_ids"] == ["40345"]
    assert values["evidence_titles"][0] == "How To Add a Support Need in MCP"
    assert values["branch_count"] == 1
    assert missing == []


def test_2_the_field_name_is_yours_to_choose():
    """The name on the left is just a label for checks and judges: rename it freely."""
    values, _ = run_fields("2. any field name works", """
fields:
  my_dummy_answer_name: {from: final, path: answer.summary}
  vamsi_test_anchor:    {from: state, path: evidence_set.anchor_page_ids}
""")
    assert values["my_dummy_answer_name"].startswith("To add a Support Need")
    assert values["vamsi_test_anchor"] == ["40345"]


def test_3_a_wrong_path_gives_none_never_a_crash():
    """A typo in a path, or a key the agent stopped logging: the value is None (NOT FOUND)."""
    values, missing = run_fields("3. wrong paths -> NOT FOUND", """
fields:
  typo_in_key:      {from: final, path: answer.sumary}
  wrong_source:     {from: state, path: answer.summary}
  not_in_trace:     {from: state, path: decision}
  index_too_far:    {from: final, path: "evidence[9].title"}
""")
    assert all(value is None for value in values.values())
    assert missing == []                       # not required, so a run would just SKIP what needs them


def test_4_required_turns_a_missing_field_into_an_error():
    """required: true -> a run ERRORs with "has the trace format changed?" instead of silently skipping."""
    _, missing = run_fields("4. required field missing", """
fields:
  answer: {from: final, path: answer.text, required: true}
""")
    assert missing == ["answer"]


def test_5_a_list_of_paths_survives_a_trace_change():
    """Several paths: the first one that finds something wins (old format first or new first)."""
    values, _ = run_fields("5. fallback paths", """
fields:
  answer: {from: final, path: [answer.text, answer.summary]}
""")
    assert values["answer"].startswith("To add a Support Need")


def test_6_extras_join_first_where_pick():
    """The optional steps after the path."""
    values, _ = run_fields("6. join / first / where + pick / matches", """
fields:
  rewritten_query:   {from: state, path: rewritten_query, join: " | "}
  first_evidence_id: {from: final, path: "evidence[].page_id", first: true}
  anchor_page_ids:   {from: state, path: evidence_set.anchor_page_ids}
  anchor_titles:     {from: final, path: evidence, where: {page_id: anchor_page_ids}, pick: title}
  used_fallback:     {from: node, node: _anchor_branch_worker, path: rationale, matches: "top Athena result"}
  content_length:    {from: message, contains: "Validation complete", regex: 'content_length=(\\d+)'}
""")
    assert values["rewritten_query"] == "add support need process"
    assert values["first_evidence_id"] == "40345"
    assert values["anchor_titles"] == ["How To Add a Support Need in MCP"]
    assert values["used_fallback"] is False
    assert values["content_length"] == 8535


@pytest.mark.parametrize("bad_line, error", [
    ("{from: finall, path: answer.summary}", "needs from: one of"),          # unknown source
    ("{from: final, pth: answer.summary}", "unknown keys"),                  # misspelt key
    ("{from: node, path: rationale}", "needs node:"),                        # node without which node
    ("{from: final, path: 'answer.]summary'}", "Invalid path"),              # broken path
])
def test_7_mistakes_in_the_yaml_stop_before_any_run(bad_line, error):
    """Config mistakes are caught when the agent loads — not halfway through a 2-hour run."""
    with pytest.raises(ConfigError, match=error) as caught:
        run_fields("7. bad yaml", f"fields:\n  answer: {bad_line}\n")
    print(f"\n--- 7. {bad_line}\n  ConfigError: {caught.value}")
