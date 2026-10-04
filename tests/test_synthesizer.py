"""Synthesizer: generation with a fake DeepEval Synthesizer, output templates, sources, config checks."""

import json

import pytest

from src.core import paths
from src.core.agent_config import load_agent
from src.core.exceptions import ConfigError
from src.onboarding.new_agent import create_agent
from src.runners.test_cases import load_cases
from src.synthesizer.generator import fetch_sources, generate_goldens
from src.synthesizer.settings import load_settings


def test_goldens_for_the_knowledge_agent(ka_copy, fake_generator):
    written = generate_goldens("knowledge_agent")
    assert len(written) == 20                                         # 10 styles x 2 pages x 1
    assert "advisor" in fake_generator["styles"][0].scenario.lower()  # instructions.md folded in
    assert "colleague" in fake_generator["styles"][0].task            # additional_guidance folded in

    folder = ka_copy / "testdata/synthetic/recoveries_commercial_bank"   # domain-wise, like the importer
    assert {p.parent for p in written} == {folder}
    cases = {}
    for path in sorted(written):                                       # the first case of each style
        case = json.loads(path.read_text())
        cases.setdefault(case["metadata"]["style"], case)
    generic = cases["direct_query"]
    assert generic["test_case_id"] == "KA_SYN_RECOVERIES_COMMERCIAL_BANK_001"
    assert generic["input"] == {"question": "Question 1 about 36626?"}             # no question_type sent
    assert "question_type" not in generic["metadata"]
    assert generic["expected"] == {"expected_answer": "Answer from the page.", "source_page_id": "36626"}
    assert generic["metadata"]["domain"] == "RECOVERIES_COMMERCIAL_BANK"
    assert generic["metadata"]["group"] == "Recoveries Commercial Bank"
    assert generic["metadata"]["source_revision"] == "7"
    assert generic["metadata"]["approval_status"] == "UNREVIEWED"
    for style, qtype in {"type_how": "how", "type_what": "what", "type_why": "why", "type_yes_no": "yes_no"}.items():
        assert cases[style]["input"]["question_type"] == qtype                     # typed: sent to the agent
        assert cases[style]["metadata"]["question_type"] == qtype

    agent = load_agent("knowledge_agent")
    assert len(load_cases(agent, agent.suite("synthetic"))) == 20
    manifest = json.loads(next((ka_copy / "synth/runs").glob("*.json")).read_text())
    assert manifest["generated"] == 20 and manifest["failed"] == []


def test_styles_pick_some_and_replace_keeps_the_others(ka_copy, fake_generator):
    generate_goldens("knowledge_agent", ids=["36626"], styles=["direct_query", "type_why"])
    folder = ka_copy / "testdata/synthetic/recoveries_commercial_bank"
    styles = sorted(json.loads(p.read_text())["metadata"]["style"] for p in folder.glob("*.json"))
    assert styles == ["direct_query", "type_why"]
    fake_generator["contexts"].clear()
    generate_goldens("knowledge_agent", ids=["36626"], styles=["type_why"], replace=True)
    styles = sorted(json.loads(p.read_text())["metadata"]["style"] for p in folder.glob("*.json"))
    assert styles == ["direct_query", "type_why"]                 # only type_why was replaced
    with pytest.raises(ConfigError, match="Unknown style"):
        generate_goldens("knowledge_agent", styles=["type_when"])


def test_goldens_add_to_existing_cases_unless_replace(ka_copy, fake_generator):
    generate_goldens("knowledge_agent", ids=["36626"])
    fake_generator["contexts"].clear()                     # run again: new cases are numbered after the old ones
    generate_goldens("knowledge_agent", ids=["36626"])
    folder = ka_copy / "testdata/synthetic/recoveries_commercial_bank"
    assert len(list(folder.glob("*.json"))) == 20                    # 10 styles, twice: numbered on
    assert (folder / "KA_SYN_RECOVERIES_COMMERCIAL_BANK_020.json").is_file()
    generate_goldens("knowledge_agent", ids=["36626"], replace=True)
    assert len(list(folder.glob("*.json"))) == 10


def test_goldens_filters_skips_and_failures(ka_copy, fake_generator):
    with pytest.raises(ConfigError, match="unknown group"):
        generate_goldens("knowledge_agent", groups=["Blackhorse"])

    fake_generator["fail_on"] = "39696"                     # one page fails: the run carries on
    fake_generator["input"] = "Same question every time?"   # duplicates are dropped
    written = generate_goldens("knowledge_agent", groups=["recoveries commercial bank"])
    assert len(written) == 1
    manifest = json.loads(next((ka_copy / "synth/runs").glob("*.json")).read_text())
    assert len(manifest["failed"]) == 10                  # one per style
    assert {s["reason"] for s in manifest["skipped"]} == {"duplicate question"}


def test_placeholder_answers_are_rejected(ka_copy, fake_generator):
    fake_generator["answer"] = "The team is [INSERT TEAM NAME]."
    assert generate_goldens("knowledge_agent") == []


def test_any_agent_any_source_any_case_shape(temp_agents, fake_generator):
    """A different agent: JSON records as the source, and its own test-case shape."""
    create_agent("analysis_agent", input_field="request")
    synth_dir = temp_agents / "analysis_agent" / "synth"
    (synth_dir / "styles").mkdir(parents=True)
    (synth_dir / "styles" / "trend.md").write_text("## task\nAsk for a trend.\n\n## input_format\n"
                                                   'JSON: {"request": "...", "metric": "..."}\n')
    (synth_dir / "sales.json").write_text(json.dumps({"rows": [
        {"sku": "A1", "region": "North", "q1": 10, "q2": 14},
        {"sku": "B2", "region": "South", "q1": 7, "q2": 5}]}))
    (synth_dir / "synth.yaml").write_text("""
source: {type: json_records, file: sales.json, records_key: rows, id_field: sku, group_field: region}
styles: {trend: {file: styles/trend.md, per_source: 1}}
output:
  folder: testdata/golden/{group_slug}
  id: "AN_{source.id}_{n:02}"
  case:
    test_case_id: "{id}"
    input: {request: "{generated.input.request}", dataset: "{source.id}"}
    expected: {metric: "{generated.input.metric}", summary: "{generated.expected_output}"}
""")
    fake_generator["input"] = '{"request": "How did sales move?", "metric": "q2 vs q1"}'
    written = generate_goldens("analysis_agent", groups=["north"])
    case = json.loads(written[0].read_text())
    assert written[0].parent.name == "north"
    assert case == {"test_case_id": "AN_A1_01",
                    "input": {"request": "How did sales move?", "dataset": "A1"},
                    "expected": {"metric": "q2 vs q1", "summary": "Answer from the page."}}
    assert '"q2": 14' in fake_generator["contexts"][0]              # whole record given to the generator

    fake_generator["input"] = "not json"                              # template field missing -> skipped
    assert generate_goldens("analysis_agent", ids=["B2"]) == []


def test_files_source_and_default_case_shape(tmp_path, monkeypatch, fake_generator):
    agents = tmp_path / "agents"
    folder = agents / "demo" / "synth"
    (folder / "documents" / "Cards").mkdir(parents=True)
    (folder / "documents" / "Cards" / "limits.md").write_text("Card limits\nThe daily limit is 500.")
    (folder / "styles").mkdir()
    (folder / "styles" / "q.md").write_text("## task\nAsk one question.\n")
    (folder / "synth.yaml").write_text("source: {type: files}\nstyles: {q: {file: styles/q.md}}\n")
    (agents / "demo" / "agent.yaml").write_text(
        "connection: {base_url: http://x, app_name: demo}\ninput_field: prompt\n"
        "suites: {golden: {testdata: testdata/golden, only: {metadata.approval_status: APPROVED}}}\n")
    monkeypatch.setattr(paths, "AGENTS_DIR", agents)

    written = generate_goldens("demo")
    case = json.loads(written[0].read_text())
    assert written[0].relative_to(agents / "demo").parts[:4] == ("testdata", "golden", "q", "cards")
    assert case["input"] == {"prompt": "Question 1 about limits?"}
    assert case["expected"]["expected_answer"] == "Answer from the page."
    agent = load_agent("demo")
    with pytest.raises(ConfigError, match="matching only"):              # nothing approved yet
        load_cases(agent, agent.suite("golden"))
    case["metadata"]["approval_status"] = "APPROVED"
    written[0].write_text(json.dumps(case))
    assert len(load_cases(agent, agent.suite("golden"))) == 1


def test_synth_config_mistakes_are_caught(ka_copy):
    style = ka_copy / "synth/styles/conditional_query.md"
    style.write_text(style.read_text().replace("## additional_guidance", "## additional guidance"))
    with pytest.raises(ConfigError, match="unknown section"):
        load_settings(load_agent("knowledge_agent"))
    style.write_text(style.read_text().replace("## additional guidance", "## additional_guidance"))

    settings = ka_copy / "synth/synth.yaml"
    settings.write_text(settings.read_text().replace("REASONING: 0.30", "REASONING: 0.50"))
    with pytest.raises(ConfigError, match="add up to 1.0"):
        load_settings(load_agent("knowledge_agent"))


def test_unknown_source_type_lists_the_available_ones(ka_copy):
    settings = ka_copy / "synth/synth.yaml"
    settings.write_text(settings.read_text().replace("type: athena_mcp", "type: sharepoint"))
    with pytest.raises(ConfigError, match="Available: .*athena_mcp.*files.*json_records"):
        fetch_sources("knowledge_agent")
