"""The Knowledge Agent parser reads the committed real traces (TC_002 simple, TC_012 complex)."""

import importlib.util
import json

from conftest import ROOT

TRACES = ROOT / "outputs" / "traces" / "knowledge_agent" / "sanity"
spec = importlib.util.spec_from_file_location("ka_parser", ROOT / "agents" / "knowledge_agent" / "parser.py")
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


def parse(case_id):
    case = json.loads((ROOT / "agents" / "knowledge_agent" / "testdata" / "sanity" / f"{case_id}.json").read_text())
    case.setdefault("expected", {})
    return parser.parse(json.loads((TRACES / f"{case_id}.json").read_text()), case)


def test_simple_query_llm_path():
    f = parse("TC_002")
    assert f["query_type"] == "simple" and f["rewritten_queries"] == ["add support need process"]
    assert f["anchor_page_ids"] == ["40345"] and f["expanded_page_ids"] == ["40017", "40015"]
    [b] = f["branches"]
    assert b["filtered_page_ids"] == ["40346", "40345", "40011"]
    assert b["llm_selected_expansion"] == [["40017", "reference"], ["40015", "exception_to"]]
    assert not (f["metadata_missing"] or f["anchor_fallback"] or f["expansion_skipped"])
    assert f["confidence"] == "HIGH" and f["caveats"] == [] and f["user_warnings"] == []
    assert f["answer"].startswith("To add a Support Need in Multi-Channel Processes")
    assert f["cited_page_ids"] == ["40345", "40015"]
    assert f["evidence_page_ids"] == ["40345", "40017", "40015"]
    assert (f["context_relevance"], f["context_applicability"], f["context_sufficiency"]) == (1.0, 1.0, 1.0)


def test_complex_query_fallback_path():
    f = parse("TC_012")
    assert f["query_type"] == "complex" and len(f["rewritten_queries"]) == 2 and len(f["branches"]) == 2
    assert f["anchor_page_ids"] == ["40022", "40015"] and f["expanded_page_ids"] == []
    assert f["metadata_missing"] and f["anchor_fallback"] and f["expansion_skipped"]
    assert f["confidence"] == "HIGH" and f["user_warnings"] == []   # degraded run, nothing surfaced


def test_stage_timings_add_up_to_the_run():
    f = parse("TC_002")
    assert set(f["stage_seconds"]) >= {"search_node", "anchor_identification_workflow", "synthesis_workflow"}
    assert 20 < sum(f["stage_seconds"].values()) < 25            # trace latency_ms is 23 676
