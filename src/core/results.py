"""Result types (check/judge, case, run) and saving/loading runs as outputs/runs/<run_id>/results.json.

Statuses: pass | fail | skip (data missing) | error (could not run).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from src.core import paths

PASS, FAIL, SKIP, ERROR = "pass", "fail", "skip", "error"


@dataclass
class Result:
    """The outcome of one check or one judge for one case."""

    name: str
    kind: str                    # "check" (deterministic) or "judge" (LLM)
    status: str
    reason: str = ""
    score: float | None = None   # judges only
    threshold: float | None = None
    engine: str = ""             # judges only: "pegasus" or "deepeval"
    group: str = ""              # checks only: its group in checks.yaml
    diagnostic: bool = False     # checks only: a FAIL is shown but does not fail the case


def check(name: str, passed: bool, reason_if_failed: str = "", group: str = "") -> Result:
    """Return a deterministic check Result; used by agents' parser.py checks()."""
    return Result(name=name, kind="check", status=PASS if passed else FAIL,
                  reason="" if passed else reason_if_failed, group=group)


@dataclass
class CaseResult:
    """One test case in one repetition: what was asked, answered, and judged."""

    case_id: str
    rep: int = 0                 # 0-based repetition number
    question: str = ""
    answer: str = ""
    expected_answer: str = ""
    latency_ms: float | None = None
    trace: str = ""              # path of the saved trace
    error: str = ""              # set when the agent or the parser failed: the case is an ERROR
    results: list[Result] = field(default_factory=list)
    # For the dashboard only, not used to decide pass/fail:
    description: str = ""
    input: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)     # every fields.yaml value for this case (long texts cut)

    @property
    def status(self) -> str:
        """Return ERROR, FAIL or PASS for the case; diagnostic check failures don't count."""
        statuses = {r.status for r in self.results if not (r.diagnostic and r.status == FAIL)}
        if self.error or ERROR in statuses:
            return ERROR
        return FAIL if FAIL in statuses else PASS


@dataclass
class Run:
    """One run (or baseline / verdict): all cases of one agent + suite."""

    agent: str
    suite: str
    build: str = ""              # label of the build under test, e.g. "1.5.0"
    kind: str = "run"            # run | baseline | verdict
    reps: int = 1
    offline: bool = False        # True when saved traces were replayed instead of calling the agent
    judge_temperature: float | None = None   # None: no judges ran
    run_id: str = ""
    started_at: str = ""
    metrics: list[str] = field(default_factory=list)
    checks: list[str] | None = None                        # None: all of them
    targets: dict = field(default_factory=dict)
    consistency: dict = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Fill started_at and a unique, time-sortable run_id ending in _<agent>_<suite>."""
        if not self.started_at:
            self.started_at = datetime.now().isoformat(timespec="seconds")
        if not self.run_id:
            # Milliseconds so quick runs in a row don't overwrite each other.
            now = datetime.now()
            stamp = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}"
            self.run_id = f"{stamp}_{flat(self.agent)}_{self.suite}"
            while (paths.OUTPUTS_DIR / "runs" / self.run_id).exists():   # same millisecond: next free id
                now = datetime.fromtimestamp(now.timestamp() + 0.001)
                self.run_id = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}_{flat(self.agent)}_{self.suite}"

    @property
    def folder(self) -> Path:
        """Return outputs/runs/<run_id>."""
        return paths.OUTPUTS_DIR / "runs" / self.run_id

    @property
    def passed(self) -> bool:
        """True when every case passed."""
        return all(c.status == PASS for c in self.cases)

    def save(self) -> Path:
        """Write results.json with each case's status and a summary; returns its path."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / "results.json"
        data = asdict(self)
        for case, raw in zip(self.cases, data["cases"], strict=True):
            raw["status"] = case.status
        from src.reporting.summary import summarise  # here, not at the top: summary imports this file
        data["summary"] = summarise([self])
        path.write_text(json.dumps(data, indent=2, default=str))
        return path


def load_run(ref: str, agent: str | None = None, suite: str | None = None) -> Run:
    """Load a saved run from 'latest' (optionally for this agent + suite), a run id, or a path.
    Raises FileNotFoundError when 'latest' finds no runs."""
    if ref == "latest":
        runs = sorted((paths.OUTPUTS_DIR / "runs").glob("*/results.json"), reverse=True)
        suffix = f"_{flat(agent)}_{suite}" if agent and suite else ""
        runs = [p for p in runs if p.parent.name.endswith(suffix)]
        if not runs:
            raise FileNotFoundError(f"No saved runs{' for ' + agent + '/' + suite if suffix else ''}")
        path = runs[0]
    else:
        path = Path(ref)
        if not path.exists():
            path = paths.OUTPUTS_DIR / "runs" / ref
        if path.is_dir():
            path = path / "results.json"
    data = json.loads(path.read_text())
    data.pop("summary", None)              # derived, recomputed when needed
    cases = []
    for raw in data.pop("cases"):
        raw.pop("status", None)            # derived, not stored on the object
        results = [Result(**r) for r in raw.pop("results")]
        if not raw.get("question") and isinstance(raw.get("input"), dict):   # older runs: errored cases had none
            raw["question"] = str(raw["input"].get("question") or "")
        cases.append(CaseResult(**raw, results=results))
    return Run(**data, cases=cases)


def flat(agent: str) -> str:
    """Return the agent name usable in a file name: 'a/b' -> 'a.b'."""
    return agent.replace("/", ".")


def recent_runs(agent: str, suite: str, count: int) -> list[Run]:
    """Return the `count` most recent saved runs of one agent + suite, oldest first."""
    found = sorted((paths.OUTPUTS_DIR / "runs").glob(f"*_{flat(agent)}_{suite}/results.json"))[-max(count, 1):]
    if not found:
        raise FileNotFoundError(f"No saved runs for {agent}/{suite} in {paths.OUTPUTS_DIR / 'runs'}")
    return [load_run(str(p)) for p in found]
