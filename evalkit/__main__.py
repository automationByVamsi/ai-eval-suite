"""
Command line. Every `make` target calls one of these.

  python -m evalkit list
  python -m evalkit new-agent <name> [--input-field question]
  python -m evalkit run      <agent> <suite> [--offline] [--no-judges] [--reps N] [--build X] [--case ID ...]
  python -m evalkit baseline <agent> <suite> [--reps N] [--build X]   (or --from-run latest|<run_id>)
  python -m evalkit verdict  <agent> <suite> [--reps N] [--build X]   (or --from-run latest|<run_id>)

Exit code is 0 when everything passed, 1 otherwise — ready for CI.
"""

from __future__ import annotations

import argparse
import sys

from evalkit import verdict
from evalkit.config import ConfigError, list_agents, load_agent
from evalkit.cortex import JudgeConfigError
from evalkit.new_agent import create_agent
from evalkit.results import load_run, print_run
from evalkit.runner import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evalkit", description="Evaluate AI agents.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show agents and their suites")
    new = commands.add_parser("new-agent", help="create agents/<name>/ from the template")
    new.add_argument("name")
    new.add_argument("--input-field", default="question", help="test case input key sent to the agent")
    for name, text in [("run", "run a suite and report pass/fail"),
                       ("baseline", "run (or reuse a run) and save it as the baseline"),
                       ("verdict", "run (or reuse a run) and compare it with the baseline")]:
        cmd = commands.add_parser(name, help=text)
        cmd.add_argument("agent")
        cmd.add_argument("suite")
        cmd.add_argument("--reps", type=int, default=1, help="run every case N times (use 3-5 for baselines)")
        cmd.add_argument("--build", default="", help="build/version label stored with the results")
        cmd.add_argument("--offline", action="store_true", help="reuse saved traces, don't call the agent")
        cmd.add_argument("--no-judges", action="store_true", help="deterministic checks only")
        cmd.add_argument("--case", action="append", dest="cases", help="only this test_case_id (repeatable)")
        if name != "run":
            cmd.add_argument("--from-run", help="use a saved run ('latest' or a run id) instead of running")
    args = parser.parse_args(argv)

    if args.command == "list":
        for agent_name in list_agents():
            agent = load_agent(agent_name)
            for suite in agent.suites.values():
                print(f"{agent_name:<24} {suite.name:<12} metrics: {', '.join(suite.metrics) or '-'}")
        return 0

    if args.command == "new-agent":
        create_agent(args.name, args.input_field)
        return 0

    if getattr(args, "from_run", None):
        run = load_run(args.from_run, args.agent, args.suite)
    else:
        run = run_suite(args.agent, args.suite, offline=args.offline, reps=args.reps, build=args.build,
                        judges=not args.no_judges, case_ids=args.cases)
        print_run(run)

    if args.command == "run":
        return 0 if run.passed else 1
    if args.command == "baseline":
        print(f"Baseline saved: {verdict.save_baseline(run)}  (commit it so the team shares it)")
        return 0
    passed, rows, baseline = verdict.compare(run)
    verdict.print_verdict(run, passed, rows, baseline)
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigError, JudgeConfigError, FileNotFoundError, ValueError) as error:
        sys.exit(f"ERROR: {error}")
