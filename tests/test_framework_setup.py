"""
Smoke: both agents load cases; live invoke when ADK is up.

  pytest tests/test_framework_setup.py -v
"""

from pathlib import Path

import pytest

from src.core.exceptions import AgentInvocationError
from src.runners.case_runner import load_cases, run_case


@pytest.mark.parametrize(
    "agent,message_key",
    [
        ("knowledge_agent", "question"),
        ("fact_find_workflow", "complaint_ref"),
    ],
)
def test_both_agents_load_and_live_one_case(agent: str, message_key: str):
    cases = load_cases(agent, "sanity")
    case = cases[0]
    assert message_key in case["input"]

    try:
        result = run_case(agent, case, "sanity", output_dir=Path("outputs/traces"))
    except AgentInvocationError as exc:
        pytest.skip(f"ADK not reachable: {exc}")

    assert result.response.answer
    assert result.saved_path and result.saved_path.exists()
