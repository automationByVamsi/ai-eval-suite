"""
Run a suite. For every test case:

  1. call the agent              Google ADK by default; an agent folder with client.py uses that
                                 (or, --offline, reuse the last saved trace)
  2. save the trace              outputs/traces/<agent>/<suite>/<case_id>.json
  3. build the fields            question/answer/contexts/expected_answer + whatever parser.py adds
  4. run deterministic checks    answer_non_empty, expected.keywords, + parser.checks()
  5. run the suite's judges      Pegasus first, DeepEval otherwise (see judges.py)
  6. record everything           outputs/runs/<run_id>/results.json
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

from evalkit.adk import call_agent
from evalkit.config import OUTPUTS_DIR, Agent, ConfigError, Suite, load_agent
from evalkit.judges import run_judge
from evalkit.results import CaseResult, Result, Run, check


def run_suite(agent_name: str, suite_name: str, *, offline: bool = False, reps: int = 1,
              build: str = "", judges: bool = True, case_ids: list[str] | None = None) -> Run:
    agent = load_agent(agent_name)
    suite = agent.suite(suite_name)
    parser = _load_module(agent, "parser.py")
    client = _load_module(agent, "client.py")
    cases = load_cases(agent, suite)
    if case_ids:
        cases = [c for c in cases if c["test_case_id"] in case_ids]

    run = Run(agent=agent.name, suite=suite.name, build=build, reps=reps, offline=offline)
    for case in cases:
        for rep in range(reps):
            label = f"{case['test_case_id']}" + (f" rep {rep + 1}/{reps}" if reps > 1 else "")
            print(f"  running {agent.name}/{suite.name} {label} ...", flush=True)
            run.cases.append(run_case(agent, suite, parser, client, case, run, rep, offline, judges))
    run.save()
    return run


def run_case(agent: Agent, suite: Suite, parser: ModuleType | None, client: ModuleType | None,
             case: dict[str, Any], run: Run, rep: int, offline: bool, judges: bool) -> CaseResult:
    case_id = case["test_case_id"]
    result = CaseResult(case_id=case_id, rep=rep)

    # 1-2. Get the trace
    latest = OUTPUTS_DIR / "traces" / agent.name / suite.name / f"{case_id}.json"
    try:
        if offline:
            if not latest.is_file():
                raise FileNotFoundError(f"no saved trace at {latest} — run once without --offline")
            trace = json.loads(latest.read_text())
            if isinstance(trace.get("raw_output"), dict) and "test_case" in trace:
                trace = trace["raw_output"]           # traces saved by the v1 framework were wrapped
        else:
            call = client.call_agent if client else call_agent
            trace = call(agent.connection, _message(agent, case))
            _save_trace(trace, latest, run.folder / "traces" / f"{case_id}__rep{rep + 1}.json")
    except Exception as exc:  # noqa: BLE001 — an unreachable agent is an ERROR, not a skip
        result.error = f"agent: {exc}"
        return result
    result.trace = str(latest)
    result.latency_ms = trace.get("latency_ms")

    # 3. Fields the checks and judges read
    fields = {
        "question": case["input"][agent.input_field],
        "answer": trace.get("agentOutput") or "",
        "contexts": list(trace.get("context") or []),
        "expected_answer": case.get("expected", {}).get("expected_answer", ""),
    }
    try:
        if parser and hasattr(parser, "parse"):
            fields.update(parser.parse(trace, case) or {})
    except Exception as exc:  # noqa: BLE001
        result.error = f"parser.parse failed: {type(exc).__name__}: {exc}"
        return result
    result.question = str(fields.get("question") or "")
    result.answer = str(fields.get("answer") or "")
    result.expected_answer = str(fields.get("expected_answer") or "")

    # 4. Deterministic checks
    result.results.extend(_standard_checks(fields, case))
    if parser and hasattr(parser, "checks"):
        try:
            result.results.extend(parser.checks(fields, case))
        except Exception as exc:  # noqa: BLE001
            result.results.append(Result("parser.checks", "check", "error", f"{type(exc).__name__}: {exc}"))

    # 5. Judges
    if judges:
        for name in suite.metrics:
            result.results.append(run_judge(name, agent.metrics[name], fields))
    return result


def load_cases(agent: Agent, suite: Suite) -> list[dict[str, Any]]:
    """Every *.json in the suite's testdata folder: one case per file, or {"cases": [...]}."""
    if not suite.testdata.is_dir():
        raise ConfigError(f"Test data folder not found: {suite.testdata} (generated suites: run make goldens first)")
    cases: list[dict[str, Any]] = []
    for path in sorted(suite.testdata.glob("*.json")):
        data = json.loads(path.read_text())
        for i, case in enumerate(data["cases"] if "cases" in data else [data]):
            case.setdefault("test_case_id", path.stem if "cases" not in data else f"{path.stem}_{i}")
            case.setdefault("expected", {})
            if agent.input_field not in (case.get("input") or {}):
                raise ConfigError(f"{path}: input.{agent.input_field} is required for {agent.name}")
            cases.append(case)
    if not cases:
        raise ConfigError(f"No test cases in {suite.testdata}")
    ids = [c["test_case_id"] for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"Duplicate test_case_id in {suite.testdata}: {duplicates}")
    return cases


def _standard_checks(fields: dict[str, Any], case: dict[str, Any]) -> list[Result]:
    answer = str(fields.get("answer") or "")
    checks = [check("answer_non_empty", bool(answer.strip()), "agent returned an empty answer")]
    for keyword in case["expected"].get("keywords") or []:
        checks.append(check(f"keyword:{keyword}", str(keyword).lower() in answer.lower(),
                            f"'{keyword}' not found in answer"))
    return checks


def _message(agent: Agent, case: dict[str, Any]) -> str:
    """The text sent to the agent: input[input_field], or message_template filled from input."""
    if agent.message_template:
        return agent.message_template.format(**case["input"])
    return str(case["input"][agent.input_field])


def _save_trace(trace: dict[str, Any], latest: Path, run_copy: Path) -> None:
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(trace, indent=2, default=str))
    run_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(latest, run_copy)


def _load_module(agent: Agent, filename: str) -> ModuleType | None:
    """agents/<name>/parser.py or client.py, if the agent has one."""
    path = agent.folder / filename
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"{agent.name}_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
