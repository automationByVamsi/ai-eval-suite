"""
Invokes a LIVE agent (or replay, for local demos) for every test case under a
tag and saves the raw trace to outputs/traces/<agent-dir>/<tag>/<id>.json.
Does NOT evaluate anything - that's what src.main / run_stage*.py are for.
This is the "capture" half of capture-then-evaluate offline replay.

    python -m scripts.capture_traces --agent-dir knowledge_agent --tag sanity
"""

import argparse
from pathlib import Path

from src.core.logging_config import setup_logging
from src.models.test_case import TestCase
from src.runners.factories import AgentFactory
from src.runners.trace_capture import capture_one


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture raw agent traces to disk (no evaluation)")
    parser.add_argument("--agent-dir", required=True, help="Folder name under testdata/, e.g. knowledge_agent")
    parser.add_argument("--tag", required=True, help="Test-data tier folder under testdata/<agent-dir>/, e.g. sanity, golden, bronze, silver, regression")
    parser.add_argument("--configs", default="configs")
    args = parser.parse_args()

    setup_logging()
    agent_factory = AgentFactory(f"{args.configs}/agents.yaml")

    testdata_dir = Path("testdata") / args.agent_dir / args.tag
    trace_dir = Path("outputs/traces") / args.agent_dir / args.tag
    trace_dir.mkdir(parents=True, exist_ok=True)

    test_case_files = sorted(testdata_dir.glob("*.json"))
    if not test_case_files:
        raise SystemExit(f"No test cases found under {testdata_dir}")

    for tc_path in test_case_files:
        test_case = TestCase.from_json_file(str(tc_path))
        out_path, latency_ms = capture_one(agent_factory, test_case, trace_dir)
        print(f"Captured {test_case.test_case_id} -> {out_path} ({latency_ms:.0f}ms)")


if __name__ == "__main__":
    main()
