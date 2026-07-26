"""
Live ADK capture for every case under a tag.

    python -m scripts.capture_traces --agent-dir knowledge_agent --tag sanity
"""

import argparse
from pathlib import Path

from src.core.logging_config import setup_logging
from src.runners.case_runner import load_cases, run_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture raw agent traces to disk (live ADK)")
    parser.add_argument("--agent-dir", required=True, help="Folder under testdata/, e.g. knowledge_agent")
    parser.add_argument("--tag", required=True, help="Data suite under testdata/<agent-dir>/, e.g. sanity")
    parser.add_argument("--configs", default="configs")
    args = parser.parse_args()

    setup_logging()
    agents_path = f"{args.configs}/agents.yaml"
    output_root = Path("outputs/traces")

    cases = load_cases(args.agent_dir, args.tag)
    for case in cases:
        result = run_case(
            args.agent_dir,
            case,
            args.tag,
            output_dir=output_root,
            agents_path=agents_path,
        )
        latency = result.response.latency_ms or 0
        print(f"Captured {result.test_case_id} -> {result.saved_path} ({latency:.0f}ms)")


if __name__ == "__main__":
    main()
