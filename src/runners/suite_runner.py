"""
Run a suite: for every case and rep, get the trace (ACT), then run checks and LLM judges (ASSERT).
A case that can't run raises CaseCouldNotRun and is recorded as an ERROR, never a pass/fail or a crash.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from src.clients.adk_client import call_agent
from src.core import paths
from src.core.agent_config import Agent, Suite, load_agent
from src.core.exceptions import ConfigError
from src.core.results import CaseResult, Result, Run, check
from src.fields.checks import fields_read, run_checks
from src.fields.extract import extract, is_empty
from src.metrics.judges import run_judge
from src.metrics.library import definition, judge_temperature
from src.runners.test_cases import load_cases


class CaseCouldNotRun(Exception):
    """A test case could not be evaluated; the message says why and the case is recorded as an ERROR."""


@dataclass
class SuiteContext:
    """Settings shared by every case of one suite run."""

    agent: Agent
    suite: Suite
    run: Run
    offline: bool                    # replay saved traces instead of calling the agent
    judges: bool                     # False: deterministic checks only (no CORTEX calls)
    client: ModuleType | None        # agents/<agent>/client.py, for agents that aren't Google ADK
    parser: ModuleType | None        # agents/<agent>/parser.py, optional Python on top of the YAML


# --- the suite --------------------------------------------------------------------------------------

def run_suite(agent_name: str, suite_name: str, *, offline: bool = False, reps: int = 1,
              build: str = "", judges: bool = True, case_ids: list[str] | None = None,
              metrics: list[str] | None = None) -> Run:
    """Run every case of one suite `reps` times, save and return the Run.
    `case_ids` / `metrics` narrow the cases / judges; judges=False runs checks only."""
    agent = load_agent(agent_name)
    suite = agent.suite(suite_name)
    if metrics:
        unknown = [m for m in metrics if m not in agent.metrics]
        if unknown:
            raise ConfigError(f"METRICS: {unknown} are not in agent.yaml metrics:. Known: {sorted(agent.metrics)}")
        suite = dataclasses.replace(suite, metrics=list(metrics))
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
    """Run one case: get the trace, read fields, check and judge. Never raises."""
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
    """Call the agent (client.py, else Google ADK) and save the trace, or replay the saved one offline.
    Raises CaseCouldNotRun on any problem."""
    latest = _latest_trace_path(ctx, case)
    rep_file = ctx.run.folder / "traces" / f"{case['test_case_id']}__rep{rep + 1}.json"
    start = time.perf_counter()
    try:
        if ctx.offline:
            return _saved_trace(latest)
        call = ctx.client.call_agent if ctx.client else call_agent
        trace = call(ctx.agent.connection, _message(ctx.agent, case))
        _save_trace(trace, latest, rep_file)
        return trace
    except Exception as exc:  # noqa: BLE001 — an unreachable agent is an ERROR, not a skip
        if case.get("expected", {}).get("expected_error") and not ctx.offline:
            # The case expects an error: the error is the answer, checked by the expected_errors checks.
            trace = {"agentOutput": "", "agent_error": str(exc), "raw_events": [],
                     "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
            _save_trace(trace, latest, rep_file)
            return trace
        raise CaseCouldNotRun(f"agent: {exc}") from exc


def read_fields(ctx: SuiteContext, case: dict[str, Any], trace: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return (fields, lookup problems): standard fields, then fields.yaml, then parser.py (later wins).
    Raises CaseCouldNotRun if a required field is missing or parser.py crashes."""
    agent = ctx.agent
    fields = {
        "question": case["input"][agent.input_field],
        "answer": trace.get("agentOutput") or "",
        "contexts": list(trace.get("context") or []),
        "expected_answer": case.get("expected", {}).get("expected_answer", ""),
        # lets checks validate the test data itself
        **{f"input_{key}": value for key, value in (case.get("input") or {}).items()},
    }
    lookup_errors: list[str] = []
    if agent.fields:
        values, missing = extract(trace, agent.fields, offline=ctx.offline, fetch=_fields_needed(ctx))
        lookup_errors = values.pop("_fetch_errors", [])
        if missing and not values.get("agent_error"):        # an error reply has no answer: that's expected
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
    """Run the suite's selected checks: built-in, checks.yaml, a failed-lookup ERROR, then parser.py checks()."""
    results = _standard_checks(fields, case, ctx.suite.checks)
    results += run_checks(ctx.agent.checks_for(ctx.suite), fields, case)
    if lookup_errors:      # judges that needed the value can't be trusted
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
    """Run the suite's LLM judges (none with JUDGES=0); a judge that can't run is an ERROR."""
    if not ctx.judges:
        return []
    return [run_judge(name, ctx.agent.metrics[name], fields) for name in ctx.suite.metrics]


# --- helpers ------------------------------------------------------------------------------------------

def _standard_checks(fields: dict[str, Any], case: dict[str, Any], selected: list[str] | None) -> list[Result]:
    """Built-in "basic" checks: non-empty answer, and each expected keyword in it."""
    def wanted(name: str) -> bool:
        return selected is None or "basic" in selected or name in selected

    answer = str(fields.get("answer") or "")
    checks = []
    if wanted("answer_non_empty") and not case["expected"].get("expected_error"):   # the error is the answer
        checks.append(check("answer_non_empty", bool(answer.strip()), "agent returned an empty answer", "basic"))
    if wanted("keywords"):
        for keyword in case["expected"].get("keywords") or []:
            checks.append(check(f"keyword:{keyword}", str(keyword).lower() in answer.lower(),
                                f"'{keyword}' not found in answer", "basic"))
    return checks


def _judge_fields(ctx: SuiteContext) -> dict[str, set[str]]:
    """Return {field: judges that read it}, honouring agent.yaml field re-mappings."""
    readers: dict[str, set[str]] = {}
    for name in ctx.suite.metrics if ctx.judges else []:
        metric = definition(name, ctx.agent.metrics[name])
        for need in metric["needs"]:
            readers.setdefault(metric.get(need, need), set()).add(name)
    return readers


def _fields_needed(ctx: SuiteContext) -> set[str]:
    """Return every field this suite's judges and checks read (only those lookups are computed)."""
    needed = set(_judge_fields(ctx))
    for spec in ctx.agent.checks_for(ctx.suite).values():
        needed |= fields_read(spec)
    if ctx.suite.checks is None and ctx.parser and hasattr(ctx.parser, "checks"):   # parser.py may read anything
        needed |= set(ctx.agent.fields)
    return needed


def _readers(ctx: SuiteContext, lookup_errors: list[str]) -> str:
    """Name the judges that needed a failed lookup (errors read "<field>: <problem>")."""
    readers = _judge_fields(ctx)
    names = sorted({j for e in lookup_errors for j in readers.get(e.split(":", 1)[0], set())})
    return " and ".join(names) if names else "this suite's checks"


DETAIL_TEXT_LIMIT = 4000


def _for_display(fields: dict[str, Any]) -> dict[str, Any]:
    """Return the fields to save for the dashboard, with long texts and lists cut."""
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
    """Build the text sent to the agent: JSON of the inputs (message format: json), the template, or the input.
    A JSON-format case with only the main input still sends it as plain text."""
    inputs = case["input"]
    if agent.message_fields:
        payload = {key: inputs[name] for key, name in agent.message_fields.items() if not is_empty(inputs.get(name))}
        if set(payload) - {key for key, name in agent.message_fields.items() if name == agent.input_field}:
            return json.dumps(payload, ensure_ascii=False)
    if agent.message_template:
        return agent.message_template.format(**inputs)
    return str(inputs[agent.input_field])


def _latest_trace_path(ctx: SuiteContext, case: dict[str, Any]) -> Path:
    """Return the path of the case's latest trace (what OFFLINE=1 replays); `traces:` can share another suite's."""
    return paths.OUTPUTS_DIR / "traces" / ctx.agent.name / ctx.suite.traces / f"{case['test_case_id']}.json"


def _saved_trace(latest: Path) -> dict[str, Any]:
    """Read the case's last saved trace, for OFFLINE=1."""
    if not latest.is_file():
        raise FileNotFoundError(f"no saved trace at {latest} — run once without OFFLINE=1")
    trace = json.loads(latest.read_text())
    # v1 traces were wrapped as {"test_case": ..., "raw_output": {...}}.
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
    """Import the agent's parser.py or client.py; None if it has none."""
    path = agent.folder / filename
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"{agent.name.replace('/', '.')}_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
