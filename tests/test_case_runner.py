"""Unit tests for load_cases / run_case helpers."""

from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.runners.case_runner import load_cases, run_case, validate_case_envelope


def test_load_cases_knowledge_agent_sanity():
    cases = load_cases("knowledge_agent", "sanity")
    ids = {c["test_case_id"] for c in cases}
    assert ids == {"TC_001", "TC_002"}
    tc1 = next(c for c in cases if c["test_case_id"] == "TC_001")
    assert "question" in tc1["input"]
    assert "agent_name" not in tc1


def test_load_cases_fact_find_sanity():
    cases = load_cases("fact_find_workflow", "sanity")
    ids = {c["test_case_id"] for c in cases}
    assert ids == {"TC_001", "TC_002"}
    tc1 = next(c for c in cases if c["test_case_id"] == "TC_001")
    assert "complaint_ref" in tc1["input"]


def test_load_cases_missing_folder():
    with pytest.raises(FileNotFoundError):
        load_cases("knowledge_agent", "does_not_exist_suite")


def test_validate_envelope_requires_input():
    with pytest.raises(ValueError, match="input"):
        validate_case_envelope({"test_case_id": "X", "input": {}})


def test_load_rejects_empty_input(tmp_path: Path):
    agent_dir = tmp_path / "demo_agent" / "sanity"
    agent_dir.mkdir(parents=True)
    (agent_dir / "bad.json").write_text(
        '{"test_case_id": "BAD", "input": {}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="input"):
        load_cases("demo_agent", "sanity", testdata_root=tmp_path)


def test_run_case_live():
    cases = load_cases("knowledge_agent", "sanity")
    case = next(c for c in cases if c["test_case_id"] == "TC_002")
    try:
        result = run_case(
            "knowledge_agent",
            case,
            "sanity",
            output_dir="outputs/traces",
        )
    except AgentInvocationError as exc:
        pytest.skip(f"ADK not reachable: {exc}")

    assert result.response.answer
    assert result.saved_path and result.saved_path.exists()
