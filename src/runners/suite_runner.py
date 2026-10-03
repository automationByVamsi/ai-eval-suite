"""
Run a suite. For every test case (and every repetition, with REPS=n):

  1. call the agent             Google ADK by default; an agent folder with client.py uses that.
                                OFFLINE=1 replays the last saved trace instead.
  2. save the trace             outputs/traces/<agent>/<suite>/<case_id>.json   (latest)
                                outputs/runs/<run_id>/traces/<case_id>__rep<n>.json   (this run)
  3. read input / expected      from the test case (runners/test_cases.py)
  4. pull fields from trace     question / answer / contexts / expected_answer, then every field
                                in agents/<agent>/fields.yaml, then parser.py parse() if there is one
  5. checks and judges          the deterministic checks the suite selects (`checks:` under the suite:
                                all by default — answer_non_empty, expected.keywords, the checks: in
                                agent.yaml, parser.py checks()), then the suite's judge metrics
  6. record everything          outputs/runs/<run_id>/results.json

Used by: the CLI (make run / baseline / verdict). Agent-specific behaviour belongs in the agent's
fields.yaml, agent.yaml (checks:), parser.py or client.py — not here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

from src.clients.adk_client import call_agent
from src.core import paths
from src.core.agent_config import Agent, Suite, load_agent
from src.core.results import CaseResult, Result, Run, check
from src.fields.checks import fields_read, run_checks
from src.fields.extract import extract, is_empty
from src.metrics.judges import run_judge
from src.metrics.library import definition
from src.runners.test_cases import load_cases


def run_suite(agent_name: str, suite_name: str, *, offline: bool = False, reps: int = 1,
              build: str = "", judges: bool = True, case_ids: list[str] | None = None) -> Run:
    """
    Run every case of one suite `reps` times and save the run.

    offline:  replay saved traces instead of calling the agent
    judges:   False runs the deterministic checks only (no CORTEX calls)
    case_ids: only these test_case_ids
    """
    agent = load_agent(agent_name)
    suite = agent.suite(suite_name)
    parser = _load_agent_module(agent, "parser.py")
    client = _load_agent_module(agent, "client.py")
    cases = load_cases(agent, suite)
    if case_ids:
        cases = [c for c in cases if c["test_case_id"] in case_ids]

    run = Run(agent=agent.name, suite=suite.name, build=build, reps=reps, offline=offline,
              metrics=list(suite.metrics) if judges else [], checks=suite.checks)
    for case in cases:
        for rep in range(reps):
            label = case["test_case_id"] + (f" rep {rep + 1}/{reps}" if reps > 1 else "")
            print(f"  running {agent.name}/{suite.name} {label} ...", flush=True)
            run.cases.append(run_case(agent, suite, parser, client, case, run, rep, offline, judges))
    run.save()
    return run


def run_case(agent: Agent, suite: Suite, parser: ModuleType | None, client: ModuleType | None,
             case: dict[str, Any], run: Run, rep: int, offline: bool, judges: bool) -> CaseResult:
    """Steps 1-5 for one case. Problems end up in the CaseResult; this never raises."""
    case_id = case["test_case_id"]
    result = CaseResult(case_id=case_id, rep=rep, description=str(case.get("description") or ""),
                        input=dict(case.get("input") or {}), expected=dict(case.get("expected") or {}))

    # 1-2. Get the trace (call the agent, or replay) and save it.
    latest = paths.OUTPUTS_DIR / "traces" / agent.name / suite.name / f"{case_id}.json"
    try:
        if offline:
            trace = _saved_trace(latest)
        else:
            call = client.call_agent if client else call_agent
            trace = call(agent.connection, _message(agent, case))
            _save_trace(trace, latest, run.folder / "traces" / f"{case_id}__rep{rep + 1}.json")
    except Exception as exc:  # noqa: BLE001 — an unreachable agent is an ERROR, not a skip
        result.error = f"agent: {exc}"
        return result
    result.trace = str(latest)
    result.latency_ms = trace.get("latency_ms")

    # 3-4. The fields checks and judges read.
    fields = {
        "question": case["input"][agent.input_field],
        "answer": trace.get("agentOutput") or "",
        "contexts": list(trace.get("context") or []),
        "expected_answer": case.get("expected", {}).get("expected_answer", ""),
    }
    fetch_errors: list[str] = []
    selected_checks = agent.checks_for(suite)
    if agent.fields:
        needed = _fields_needed(agent, suite, selected_checks, judges, parser)
        values, missing = extract(trace, agent.fields, offline=offline, fetch=needed)
        fetch_errors = values.pop("_fetch_errors", [])
        if missing:
            result.error = (f"required field(s) {missing} not found in the trace — has the trace format changed? "
                            f"Check with: make fields AGENT={agent.name} SUITE={suite.name} CASE={case_id}")
            return result
        fields.update({k: v for k, v in values.items() if not is_empty(v) or k not in fields})
    try:
        if parser and hasattr(parser, "parse"):
            fields.update(parser.parse(trace, case) or {})
    except Exception as exc:  # noqa: BLE001
        result.error = f"parser.parse failed: {type(exc).__name__}: {exc}"
        return result
    result.question = str(fields.get("question") or "")
    result.answer = str(fields.get("answer") or "")
    result.expected_answer = str(fields.get("expected_answer") or "")
    result.details = _for_display(fields)

    # 5a. Deterministic checks — the ones this suite selects (all, none, or a list of names / groups).
    result.results.extend(_standard_checks(fields, case, suite.checks))
    result.results.extend(run_checks(selected_checks, fields, case))
    if fetch_errors:      # e.g. the source is unreachable: judges that needed that value can't be trusted
        result.results.append(Result(
            "lookup", "check", "error", group="setup",
            reason=f"A lookup failed (agents/{agent.name}/lookups.py), so "
                   f"{_readers(agent, suite, judges, fetch_errors)} could not run: " + "; ".join(fetch_errors)))
    if parser and hasattr(parser, "checks") and suite.checks is None:
        try:
            result.results.extend(parser.checks(fields, case))
        except Exception as exc:  # noqa: BLE001
            result.results.append(Result("parser.checks", "check", "error", f"{type(exc).__name__}: {exc}"))

    # 5b. LLM judges — only the metrics this suite lists.
    if judges:
        for name in suite.metrics:
            result.results.append(run_judge(name, agent.metrics[name], fields))
    return result


def _standard_checks(fields: dict[str, Any], case: dict[str, Any], selected: list[str] | None) -> list[Result]:
    """Checks every agent gets (group "basic"): a non-empty answer, and each of expected.keywords in it."""
    def wanted(name: str) -> bool:
        return selected is None or "basic" in selected or name in selected

    answer = str(fields.get("answer") or "")
    checks = []
    if wanted("answer_non_empty"):
        checks.append(check("answer_non_empty", bool(answer.strip()), "agent returned an empty answer", "basic"))
    if wanted("keywords"):
        for keyword in case["expected"].get("keywords") or []:
            checks.append(check(f"keyword:{keyword}", str(keyword).lower() in answer.lower(),
                                f"'{keyword}' not found in answer", "basic"))
    return checks


def _judge_fields(agent: Agent, suite: Suite, judges: bool) -> dict[str, set[str]]:
    """{field: the suite's judges that read it}, with agent.yaml re-mappings (answer: rewritten_query)."""
    readers: dict[str, set[str]] = {}
    for name in suite.metrics if judges else []:
        metric = definition(name, agent.metrics[name])
        for need in metric["needs"]:
            readers.setdefault(metric.get(need, need), set()).add(name)
    return readers


def _fields_needed(agent: Agent, suite: Suite, checks: dict[str, dict[str, Any]], judges: bool,
                   parser: ModuleType | None) -> set[str]:
    """Every field this suite's judges and checks read: only those `from: lookup` fields are computed."""
    needed = set(_judge_fields(agent, suite, judges))
    for spec in checks.values():
        needed |= fields_read(spec)
    if suite.checks is None and parser and hasattr(parser, "checks"):   # parser.py checks may read anything
        needed |= set(agent.fields)
    return needed


def _readers(agent: Agent, suite: Suite, judges: bool, fetch_errors: list[str]) -> str:
    """Which judges needed the value that could not be looked up (errors read "<field>: <problem>")."""
    readers = _judge_fields(agent, suite, judges)
    names = sorted({j for e in fetch_errors for j in readers.get(e.split(":", 1)[0], set())})
    return " and ".join(names) if names else "this suite's checks"


DETAIL_TEXT_LIMIT = 4000


def _for_display(fields: dict[str, Any]) -> dict[str, Any]:
    """The extracted fields, saved with the case for the dashboard. Long texts are cut."""
    def cut(value: Any) -> Any:
        if isinstance(value, str) and len(value) > DETAIL_TEXT_LIMIT:
            return value[:DETAIL_TEXT_LIMIT] + f"… [{len(value) - DETAIL_TEXT_LIMIT} more characters]"
        if isinstance(value, list):
            return [cut(v) for v in value[:50]]
        if isinstance(value, dict):
            return {k: cut(v) for k, v in list(value.items())[:50]}
        return value

    skip = {"question", "answer", "expected_answer"}
    return {k: cut(v) for k, v in fields.items() if k not in skip}


def _message(agent: Agent, case: dict[str, Any]) -> str:
    """The text sent to the agent: input[input_field], or message_template filled from input."""
    if agent.message_template:
        return agent.message_template.format(**case["input"])
    return str(case["input"][agent.input_field])


def _saved_trace(latest: Path) -> dict[str, Any]:
    """The last saved trace of a case, for OFFLINE=1."""
    if not latest.is_file():
        raise FileNotFoundError(f"no saved trace at {latest} — run once without OFFLINE=1")
    trace = json.loads(latest.read_text())
    # Traces saved by the v1 framework were wrapped as {"test_case": ..., "raw_output": {...}}.
    if isinstance(trace.get("raw_output"), dict) and "test_case" in trace:
        trace = trace["raw_output"]
    return trace


def _save_trace(trace: dict[str, Any], latest: Path, run_copy: Path) -> None:
    """Write the trace as the case's latest trace and keep a copy with this run."""
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(trace, indent=2, default=str))
    run_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(latest, run_copy)


def _load_agent_module(agent: Agent, filename: str) -> ModuleType | None:
    """Import agents/<name>/parser.py or client.py, if the agent has one."""
    path = agent.folder / filename
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"{agent.name}_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
