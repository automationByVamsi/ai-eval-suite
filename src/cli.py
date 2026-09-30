"""
Command line. Every `make` target runs one of these (`make help` shows the make versions):

  python -m src doctor [--no-ping]                                     check this machine is ready
  python -m src list
  python -m src new-agent <name> [--input-field question]
  python -m src sources  <agent> [--group G] [--ids ID ...]              fetch synthesizer documents
  python -m src goldens  <agent> [--group G] [--ids ID ...] [--replace]  generate test cases
  python -m src fields   <agent> [--suite S] [--case ID ...] [--trace FILE]   preview fields.yaml on saved traces
  python -m src import-cases <agent> <file.xlsx|.csv> [--mapping M] [--sheet S] [--dry-run]
  python -m src run      <agent> <suite> [--offline] [--no-judges] [--reps N] [--build X] [--case ID ...]
  python -m src baseline <agent> <suite> [--reps N] [--build X]   (or --from-run latest|<run_id>)
  python -m src verdict  <agent> <suite> [--reps N] [--build X]   (or --from-run latest|<run_id>)

Exit code: 0 when everything passed, 1 otherwise — ready for CI.
"""

from __future__ import annotations

import argparse
import sys

from src.core.agent_config import list_agents, load_agent
from src.core.exceptions import ConfigError
from src.core.results import load_run
from src.fields.preview import preview
from src.importers.cases import import_cases
from src.onboarding.doctor import run_doctor
from src.onboarding.new_agent import create_agent
from src.reporting.console import print_run, print_verdict
from src.runners.suite_runner import run_suite
from src.synthesizer import generator
from src.verdict.baseline import save_baseline
from src.verdict.compare import compare


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src", description="Evaluate AI agents.")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="check Python env, Pegasus, env files, certificates and CORTEX")
    doctor.add_argument("--no-ping", action="store_true", help="skip the test call to CORTEX")
    commands.add_parser("list", help="show agents and their suites")

    new = commands.add_parser("new-agent", help="create agents/<name>/ from the template")
    new.add_argument("name")
    new.add_argument("--input-field", default="question", help="test case input key sent to the agent")

    for name, text in [("sources", "fetch synthesizer documents into agents/<agent>/synth/cache/"),
                       ("goldens", "generate test cases from the synthesizer documents")]:
        cmd = commands.add_parser(name, help=text)
        cmd.add_argument("agent")
        cmd.add_argument("--group", action="append", help="only this group/domain (repeatable, or comma-separated)")
        cmd.add_argument("--ids", nargs="+", help="only these document ids")
        if name == "goldens":
            cmd.add_argument("--replace", action="store_true",
                             help="clear the folders being generated into (after generation succeeds)")

    fields = commands.add_parser("fields", help="show what fields.yaml (and the checks) give for saved traces")
    fields.add_argument("agent")
    fields.add_argument("--suite", default="sanity", help="whose saved traces to read (default: sanity)")
    fields.add_argument("--case", action="append", dest="cases", help="only this test_case_id (repeatable)")
    fields.add_argument("--trace", help="read this trace file instead")

    imp = commands.add_parser("import-cases", help="turn a spreadsheet of test cases into test case JSON files")
    imp.add_argument("agent")
    imp.add_argument("file", help=".xlsx or .csv")
    imp.add_argument("--mapping", help="agents/<agent>/importers/<mapping>.yaml (default: the only one)")
    imp.add_argument("--sheet", help="sheet name (default: the mapping's sheet, else the first sheet)")
    imp.add_argument("--dry-run", action="store_true", help="show what would be written, write nothing")

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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command; returns the exit code."""
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        return run_doctor(ping=not args.no_ping)

    if args.command == "list":
        for agent_name in list_agents():
            agent = load_agent(agent_name)
            for suite in agent.suites.values():
                print(f"{agent_name:<24} {suite.name:<12} metrics: {', '.join(suite.metrics) or '-'}")
        return 0

    if args.command == "new-agent":
        create_agent(args.name, args.input_field)
        return 0

    if args.command in ("sources", "goldens"):
        # GROUP="A,B" from make arrives as one value; --group can also be repeated.
        groups = [g.strip() for value in args.group or [] for g in value.split(",") if g.strip()] or None
        if args.command == "sources":
            generator.fetch_sources(args.agent, groups, args.ids)
        else:
            generator.generate_goldens(args.agent, groups, args.ids, replace=args.replace)
        return 0

    if args.command == "fields":
        return preview(args.agent, args.suite, args.cases, args.trace)

    if args.command == "import-cases":
        import_cases(args.agent, args.file, mapping=args.mapping, sheet=args.sheet, dry_run=args.dry_run)
        return 0

    # run / baseline / verdict: get a run (new, or a saved one), then act on it.
    if getattr(args, "from_run", None):
        run = load_run(args.from_run, args.agent, args.suite)
    else:
        run = run_suite(args.agent, args.suite, offline=args.offline, reps=args.reps, build=args.build,
                        judges=not args.no_judges, case_ids=args.cases)
        print_run(run)

    if args.command == "run":
        return 0 if run.passed else 1
    if args.command == "baseline":
        print(f"Baseline saved: {save_baseline(run)}  (commit it so the team shares it)")
        return 0
    passed, rows, baseline = compare(run)
    print_verdict(run, passed, rows, baseline)
    return 0 if passed else 1


def run_cli() -> int:
    """main(), with the framework's own errors printed as one line instead of a traceback."""
    try:
        return main()
    except (ConfigError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
