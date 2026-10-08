"""
Run a suite: every test case, `REPS` times each. Read it top to bottom — it is written like a test case.

    run_suite      the loop: for every case, for every repetition -> run_case
    run_case       one test case:
                     ACT     get_trace                  call the agent (or replay the saved trace, OFFLINE=1)
                             read_fields                what the agent said and did, read from its trace
                     ASSERT  run_deterministic_checks   rules with a clear yes / no (checks.yaml)
                             run_llm_judges             the suite's LLM judges (agent.yaml metrics)

Where things go:
  the trace     outputs/traces/<agent>/<suite>/<case_id>.json            (the latest, used by OFFLINE=1)
                outputs/runs/<run_id>/traces/<case_id>__rep<n>.json       (a copy kept with this run)
  the results   outputs/runs/<run_id>/results.json

When a case can't be run (agent unreachable, the trace format changed, parser.py crashed), the step
raises CaseCouldNotRun with a clear message, and run_case records it as the case's ERROR — never a pass,
never a fail, never a crash of the whole run.

Used by: the CLI (make run / baseline / verdict). Agent-specific behaviour belongs in the agent's folder
(agent.yaml, fields.yaml, checks.yaml, client.py, parser.py) — not here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import dataclass
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
from src.metrics.library import definition, judge_temperature
from src.runners.test_cases import load_cases


class CaseCouldNotRun(Exception):
    """A test case could not be evaluated. The message says why; the case is recorded as an ERROR."""


@dataclass
class SuiteContext:
    """Everything that stays the same for every case of one suite run."""

    agent: Agent
    suite: Suite
    run: Run
    offline: bool                    # replay saved traces instead of calling the agent
    judges: bool                     # False: deterministic checks only (no CORTEX calls)
    client: ModuleType | None        # agents/<agent>/client.py, for agents that aren't Google ADK
    parser: ModuleType | None        # agents/<agent>/parser.py, optional Python on top of the YAML


# --- the suite --------------------------------------------------------------------------------------

def run_suite(agent_name: str, suite_name: str, *, offline: bool = False, reps: int = 1,
              build: str = "", judges: bool = True, case_ids: list[str] | None = None) -> Run:
    """
    Run every case of one suite `reps` times, then save the run.

    offline:  replay saved traces instead of calling the agent
    judges:   False runs the deterministic checks only (no CORTEX calls)
    case_ids: only these test_case_ids
    """
    agent = load_agent(agent_name)
    suite = agent.suite(suite_name)
    cases = load_cases(agent, suite)
    if case_ids:
        cases = [c for c in cases if c["test_case_id"] in case_ids]

    run = Run(agent=agent.name, suite=suite.name, build=build, reps=reps, offline=offline,
              judge_temperature=judge_temperature() if judges and suite.metrics else None,
              metrics=list(suite.metrics) if judges else [], checks=suite.checks,
              targets=dict(suite.targets), consistency=dict(agent.consistency))
    ctx = SuiteContext(agent=agent, suite=suite, run=run, offline=offline, judges=judges,
                       parser=_load_agent_module(agent, "parser.py"),
                       client=_load_agent_module(agent, "client.py"))

    for case in cases:
        for rep in range(reps):
            label = case["test_case_id"] + (f" rep {rep + 1}/{reps}" if reps > 1 else "")
            print(f"  running {agent.name}/{suite.name} {label} ...", flush=True)
            run.cases.append(run_case(ctx, case, rep))
    run.save()
    return run


# --- one test case ----------------------------------------------------------------------------------

def run_case(ctx: SuiteContext, case: dict[str, Any], rep: int) -> CaseResult:
    """One test case: ask the agent, read its trace, then check and judge the answer. Never raises."""
    result = CaseResult(case_id=case["test_case_id"], rep=rep, description=str(case.get("description") or ""),
                        input=dict(case.get("input") or {}), expected=dict(case.get("expected") or {}))
    try:
        # ACT
        trace = get_trace(ctx, case, rep)
        result.trace = str(_latest_trace_path(ctx, case))
        result.latency_ms = trace.get("latency_ms")
        fields, lookup_errors = read_fields(ctx, case, trace)
    except CaseCouldNotRun as problem:
        result.error = str(problem)
        return result

    # What was asked and answered (shown on the console and the dashboard).
    result.question = str(fields.get("question") or "")
    result.answer = str(fields.get("answer") or "")
    result.expected_answer = str(fields.get("expected_answer") or "")
    result.details = _for_display(fields)

    # ASSERT
    result.results += run_deterministic_checks(ctx, case, fields, lookup_errors)
    result.results += run_llm_judges(ctx, fields)
    return result


# --- the steps ----------------------------------------------------------------------------------------

def get_trace(ctx: SuiteContext, case: dict[str, Any], rep: int) -> dict[str, Any]:
    """
    The agent's trace for this case: call the agent (its client.py, else Google ADK) and save the trace,
    or with OFFLINE=1 read the last saved one. Any problem -> CaseCouldNotRun("agent: ...").
    """
    latest = _latest_trace_path(ctx, case)
    try:
        if ctx.offline:
            return _saved_trace(latest)
        call = ctx.client.call_agent if ctx.client else call_agent
        trace = call(ctx.agent.connection, _message(ctx.agent, case))
        _save_trace(trace, latest, ctx.run.folder / "traces" / f"{case['test_case_id']}__rep{rep + 1}.json")
        return trace
    except Exception as exc:  # noqa: BLE001 — an unreachable agent is an ERROR, not a skip
        raise CaseCouldNotRun(f"agent: {exc}") from exc


def read_fields(ctx: SuiteContext, case: dict[str, Any], trace: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    What the checks and judges look at, in three layers (a later layer wins):
      1. the standard fields   question, answer, contexts, expected_answer
      2. fields.yaml           every field of the agent (lookups only when this suite needs them)
      3. parser.py parse()     if the agent has one
    Returns (fields, lookup problems). A required field that found nothing, or a crash in parser.py,
    -> CaseCouldNotRun.
    """
    agent = ctx.agent
    fields = {
        "question": case["input"][agent.input_field],
        "answer": trace.get("agentOutput") or "",
        "contexts": list(trace.get("context") or []),
        "expected_answer": case.get("expected", {}).get("expected_answer", ""),
    }
    lookup_errors: list[str] = []
    if agent.fields:
        values, missing = extract(trace, agent.fields, offline=ctx.offline, fetch=_fields_needed(ctx))
        lookup_errors = values.pop("_fetch_errors", [])
        if missing:
            raise CaseCouldNotRun(
                f"required field(s) {missing} not found in the trace — has the trace format changed? "
                f"Check with: make fields AGENT={agent.name} SUITE={ctx.suite.name} CASE={case['test_case_id']}")
        fields.update({k: v for k, v in values.items() if not is_empty(v) or k not in fields})
    if ctx.parser and hasattr(ctx.parser, "parse"):
        try:
            fields.update(ctx.parser.parse(trace, case) or {})
        except Exception as exc:  # noqa: BLE001
            raise CaseCouldNotRun(f"parser.parse failed: {type(exc).__name__}: {exc}") from exc
    return fields, lookup_errors


def run_deterministic_checks(ctx: SuiteContext, case: dict[str, Any], fields: dict[str, Any],
                             lookup_errors: list[str]) -> list[Result]:
    """
    The checks this suite selects (`checks:` under the suite — all by default), in this order:
    the built-in ones (answer_non_empty, expected.keywords), checks.yaml, a failed lookup (as an ERROR),
    and parser.py checks() when the suite runs all checks.
    """
    results = _standard_checks(fields, case, ctx.suite.checks)
    results += run_checks(ctx.agent.checks_for(ctx.suite), fields, case)
    if lookup_errors:      # e.g. Athena was unreachable: the judges that needed that value can't be trusted
        results.append(Result(
            "lookup", "check", "error", group="setup",
            reason=f"A lookup failed (agents/{ctx.agent.name}/lookups.py), so {_readers(ctx, lookup_errors)} "
                   f"could not run: " + "; ".join(lookup_errors)))
    if ctx.parser and hasattr(ctx.parser, "checks") and ctx.suite.checks is None:
        try:
            results += ctx.parser.checks(fields, case)
        except Exception as exc:  # noqa: BLE001
            results.append(Result("parser.checks", "check", "error", f"{type(exc).__name__}: {exc}"))
    return results


def run_llm_judges(ctx: SuiteContext, fields: dict[str, Any]) -> list[Result]:
    """Each LLM judge the suite lists (none with JUDGES=0). A judge that can't run is an ERROR, not a score."""
    if not ctx.judges:
        return []
    return [run_judge(name, ctx.agent.metrics[name], fields) for name in ctx.suite.metrics]


# --- helpers ------------------------------------------------------------------------------------------

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


def _judge_fields(ctx: SuiteContext) -> dict[str, set[str]]:
    """{field: the suite's judges that read it}, with agent.yaml re-mappings (answer: rewritten_query)."""
    readers: dict[str, set[str]] = {}
    for name in ctx.suite.metrics if ctx.judges else []:
        metric = definition(name, ctx.agent.metrics[name])
        for need in metric["needs"]:
            readers.setdefault(metric.get(need, need), set()).add(name)
    return readers


def _fields_needed(ctx: SuiteContext) -> set[str]:
    """Every field this suite's judges and checks read: only those `lookup:` fields are computed."""
    needed = set(_judge_fields(ctx))
    for spec in ctx.agent.checks_for(ctx.suite).values():
        needed |= fields_read(spec)
    if ctx.suite.checks is None and ctx.parser and hasattr(ctx.parser, "checks"):   # parser.py may read anything
        needed |= set(ctx.agent.fields)
    return needed


def _readers(ctx: SuiteContext, lookup_errors: list[str]) -> str:
    """Which judges needed the value that could not be looked up (errors read "<field>: <problem>")."""
    readers = _judge_fields(ctx)
    names = sorted({j for e in lookup_errors for j in readers.get(e.split(":", 1)[0], set())})
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
    """
    The text sent to the agent: input[input_field]; or message_template filled from input; or, with
    `message: {format: json, ...}` in agent.yaml, the inputs as a JSON object (only the ones this
    case has — a case with just the main input still sends it as plain text, as before).
    """
    inputs = case["input"]
    if agent.message_fields:
        payload = {key: inputs[name] for key, name in agent.message_fields.items() if not is_empty(inputs.get(name))}
        if set(payload) - {key for key, name in agent.message_fields.items() if name == agent.input_field}:
            return json.dumps(payload, ensure_ascii=False)
    if agent.message_template:
        return agent.message_template.format(**inputs)
    return str(inputs[agent.input_field])


def _latest_trace_path(ctx: SuiteContext, case: dict[str, Any]) -> Path:
    """outputs/traces/<agent>/<suite>/<case_id>.json — the case's latest trace (what OFFLINE=1 replays)."""
    return paths.OUTPUTS_DIR / "traces" / ctx.agent.name / ctx.suite.name / f"{case['test_case_id']}.json"


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
