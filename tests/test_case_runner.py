"""Unit tests for load_cases / run_case (load is offline; live invoke is optional)."""

from pathlib import Path

import pytest

from src.runners.case_runner import load_cases, run_case


def test_load_cases_knowledge_agent_sanity():
    cases = load_cases("knowledge_agent", "sanity")
    ids = {c["test_case_id"] for c in cases}
    assert "TC_001" in ids
    assert "TC_002" in ids
    tc1 = next(c for c in cases if c["test_case_id"] == "TC_001")
    assert "question" in tc1["input"]


def test_load_cases_missing_folder():
    with pytest.raises(FileNotFoundError):
        load_cases("knowledge_agent", "does_not_exist_suite")


def test_run_case_replay_from_existing_trace(tmp_path: Path):
    """Replay mode reads a previously saved ADK JSON (no network)."""
    agent = "knowledge_agent"
    suite = "sanity"
    case_id = "TC_001"
    # Use a tiny fake saved output under tmp_path
    save_dir = tmp_path / agent / suite
    save_dir.mkdir(parents=True)
    (save_dir / f"{case_id}.json").write_text(
        '{"agentOutput": "hello from replay", "sessionId": "s1", "raw_events": []}',
        encoding="utf-8",
    )
    case = {"test_case_id": case_id, "input": {"question": "ignored in replay"}}
    result = run_case(agent, case, suite, output_dir=tmp_path, mode="replay")
    assert result.response.answer == "hello from replay"
    assert result.saved_path is not None
    assert result.test_case_id == case_id


def test_run_case_live_smoke():
    """Optional live call — skipped unless RUN_LIVE=1."""
    import os

    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("Set RUN_LIVE=1 to hit a real knowledge_agent")

    cases = load_cases("knowledge_agent", "sanity")
    case = next(c for c in cases if c["test_case_id"] == "TC_002")
    result = run_case("knowledge_agent", case, "sanity", output_dir="outputs", mode="live")
    assert result.response.answer
    assert result.saved_path and result.saved_path.exists()
