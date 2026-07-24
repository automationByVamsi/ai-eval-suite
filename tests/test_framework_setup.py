"""
Example QA pattern: load → run_case → assert.

  pytest tests/test_framework_setup.py -v
  RUN_LIVE=1 pytest tests/test_framework_setup.py -v   # hits real ADK
"""

from pathlib import Path

import pytest

from src.runners.case_runner import load_cases, run_case


AGENT = "knowledge_agent"
DATA_SUITE = "sanity"


@pytest.fixture(scope="module")
def sanity_cases():
    return load_cases(AGENT, DATA_SUITE)


@pytest.mark.parametrize(
    "case_id",
    ["TC_001", "TC_002"],
)
def test_sanity_replay_or_skip(sanity_cases, case_id: str):
    """
    Default: replay from outputs/<agent>/<suite>/ if present.
    With RUN_LIVE=1: call ADK and overwrite that file.
    """
    import os

    case = next(c for c in sanity_cases if c["test_case_id"] == case_id)
    mode = "live" if os.environ.get("RUN_LIVE") == "1" else "replay"
    out = Path("outputs")

    if mode == "replay":
        expected = out / AGENT / DATA_SUITE / f"{case_id}.json"
        if not expected.exists():
            pytest.skip(f"No saved output at {expected}; run with RUN_LIVE=1 first")

    result = run_case(AGENT, case, DATA_SUITE, output_dir=out, mode=mode)

    # --- validation only (QA owns this) ---
    assert result.response.answer, "empty agent answer"
    assert result.saved_path and result.saved_path.exists()
