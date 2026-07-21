"""
CLI: generate Fact Find aggregated payloads (ground truth) before agent eval.

Examples:
  python -m scripts.generate_factfind_payloads
  python -m scripts.generate_factfind_payloads data/fact_find_workflow/complaint-references.json
  python -m scripts.generate_factfind_payloads --refs NC10010556,NC10001212

Requires env vars from .env.factfind.api.example (and optional APIC mTLS certs).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE). Does not override existing env."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Fact Find aggregated payloads")
    parser.add_argument(
        "refs_file",
        nargs="?",
        default=None,
        help="Path to complaint-references.json (default: data/fact_find_workflow/complaint-references.json)",
    )
    parser.add_argument(
        "--refs",
        default=None,
        help="Comma-separated complaint refs to generate (skips the JSON file)",
    )
    parser.add_argument(
        "--env-file",
        default=".env.factfind.api",
        help="Optional dotenv file to load (default: .env.factfind.api)",
    )
    parser.add_argument(
        "--groups",
        default="positive,edge",
        help="Comma-separated groups from the refs file (default: positive,edge)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory for aggregated payloads",
    )
    args = parser.parse_args()

    _load_dotenv(Path(args.env_file))

    from src.factfind import config
    from src.factfind.generate import generate_all, generate_expected_payload

    output_dir = Path(args.output_dir) if args.output_dir else config.DEFAULT_OUTPUT_DIR

    if args.refs:
        refs = [r.strip() for r in args.refs.split(",") if r.strip()]
        failed = 0
        for ref in refs:
            try:
                generate_expected_payload(ref, output_dir=output_dir)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAILED {ref}: {exc}")
        return 1 if failed else 0

    refs_path = Path(args.refs_file) if args.refs_file else config.DEFAULT_REFS_FILE
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    summary = generate_all(refs_path, groups=groups, output_dir=output_dir)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
