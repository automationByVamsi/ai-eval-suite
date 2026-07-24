"""
Invokes a LIVE ADK agent for every test case under a tag and saves
the raw trace to outputs/traces/<agent-dir>/<tag>/<id>.json.
Does NOT evaluate — run the agent's pytest suite for that.

    python -m scripts.capture_traces --agent-dir knowledge_agent --tag sanity
"""

import argparse
from pathlib import Path

from src.core.logging_config import setup_logging
from src.models.test_case import TestCase
from src.runners.trace_capture import capture_one


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture raw agent traces to disk (no evaluation)")
    parser.add_argument("--agent-dir", required=True, help="Folder name under testdata/, e.g. knowledge_agent")
    parser.add_argument(
        "--tag",
        required=True,
        help="Test-data tier under testdata/<agent-dir>/, e.g. sanity",
    )
    parser.add_argument("--configs", default="configs")
    args = parser.parse_args()

    setup_logging()

    testdata_dir = Path("testdata") / args.agent_dir / args.tag
    trace_dir = Path("outputs/traces") / args.agent_dir / args.tag
    trace_dir.mkdir(parents=True, exist_ok=True)
    agents_path = f"{args.configs}/agents.yaml"

    test_case_files = sorted(testdata_dir.glob("*.json"))
    if not test_case_files:
        raise SystemExit(f"No test cases found under {testdata_dir}")

    for tc_path in test_case_files:
        test_case = TestCase.from_json_file(str(tc_path))
        out_path, latency_ms = capture_one(test_case, trace_dir, agents_path=agents_path)
        print(f"Captured {test_case.test_case_id} -> {out_path} ({latency_ms:.0f}ms)")


if __name__ == "__main__":
    main()
