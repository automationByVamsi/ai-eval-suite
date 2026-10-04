"""
What a result is, and how a run is saved to and loaded from disk.

Every check and every judge produces one `Result` with one of four statuses:
    pass | fail | skip (the case doesn't have the data this needs) | error (it could not run)

A case passes when nothing in it failed or errored. A run passes when every case passed.
A run is saved as outputs/runs/<run_id>/results.json — the dashboard and the verdict read that file.

Used by: the runner (creates results), parsers (`check()`), reporting and verdict (read them).
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
    status: str                  # PASS / FAIL / SKIP / ERROR
    reason: str = ""
    score: float | None = None   # judges only
    threshold: float | None = None
    engine: str = ""             # judges only: "pegasus" or "deepeval"
    group: str = ""              # checks only: the group it is written under in agent.yaml (dashboard)


def check(name: str, passed: bool, reason_if_failed: str = "", group: str = "") -> Result:
    """A deterministic check — the helper agents' parser.py files use in checks()."""
    return Result(name=name, kind="check", status=PASS if passed else FAIL,
                  reason="" if passed else reason_if_failed, group=group)


@dataclass
class CaseResult:
    """Everything about one test case in one repetition: what was asked, answered, and judged."""

    case_id: str
    rep: int = 0                 # 0-based repetition number (REPS=5 -> 0..4)
    question: str = ""
    answer: str = ""
    expected_answer: str = ""
    latency_ms: float | None = None
    trace: str = ""              # path of the saved trace
    error: str = ""              # set when the agent or the parser failed: the case is an ERROR
    results: list[Result] = field(default_factory=list)
    # For the dashboard (not used to decide pass/fail):
    description: str = ""        # the test case's description
    input: dict = field(default_factory=dict)       # the test case's input block
    expected: dict = field(default_factory=dict)    # the test case's expected block
    details: dict = field(default_factory=dict)     # every fields.yaml value for this case (long texts cut)

    @property
    def status(self) -> str:
        statuses = {r.status for r in self.results}
        if self.error or ERROR in statuses:
            return ERROR
        return FAIL if FAIL in statuses else PASS


@dataclass
class Run:
    """One `make run` (or baseline / verdict): all cases of one agent + suite."""

    agent: str
    suite: str
    build: str = ""              # label of the build under test, e.g. "1.5.0"
    reps: int = 1
    offline: bool = False        # True when saved traces were replayed instead of calling the agent
    run_id: str = ""
    started_at: str = ""
    metrics: list[str] = field(default_factory=list)       # the judges this suite runs
    checks: list[str] | None = None                        # the checks it runs (None: all of them)
    targets: dict = field(default_factory=dict)            # release targets of the suite (agent.yaml)
    consistency: dict = field(default_factory=dict)        # consistency rules for REPS > 1 (agent.yaml)
    cases: list[CaseResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now().isoformat(timespec="seconds")
        if not self.run_id:
            # Sortable by time, and ends in _<agent>_<suite> so load_run('latest', agent, suite) can filter.
            # Milliseconds too: quick runs in a row (e.g. OFFLINE=1 in a loop) must not overwrite each other.
            now = datetime.now()
            stamp = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}"
            self.run_id = f"{stamp}_{self.agent}_{self.suite}"
            while (paths.OUTPUTS_DIR / "runs" / self.run_id).exists():   # same millisecond: next free id
                now = datetime.fromtimestamp(now.timestamp() + 0.001)
                self.run_id = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}_{self.agent}_{self.suite}"

    @property
    def folder(self) -> Path:
        return paths.OUTPUTS_DIR / "runs" / self.run_id

    @property
    def passed(self) -> bool:
        return all(c.status == PASS for c in self.cases)

    def save(self) -> Path:
        """Write results.json (with each case's status, so readers don't have to recompute it)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / "results.json"
        data = asdict(self)
        for case, raw in zip(self.cases, data["cases"], strict=True):
            raw["status"] = case.status
        from src.reporting.summary import summarise  # here, not at the top: summary imports this file
        data["summary"] = summarise([self])            # rates per check / judge (read-only, for readers)
        path.write_text(json.dumps(data, indent=2, default=str))
        return path


def load_run(ref: str, agent: str | None = None, suite: str | None = None) -> Run:
    """
    Load a saved run.

    ref: 'latest' (newest run, optionally only for this agent + suite), a run id
         (folder name under outputs/runs/), or a path to a run folder / results.json.
    """
    if ref == "latest":
        runs = sorted((paths.OUTPUTS_DIR / "runs").glob("*/results.json"), reverse=True)
        suffix = f"_{agent}_{suite}" if agent and suite else ""
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
    data.pop("summary", None)              # derived from the cases, recomputed when needed
    cases = []
    for raw in data.pop("cases"):
        raw.pop("status", None)            # derived from the results, not stored on the object
        results = [Result(**r) for r in raw.pop("results")]
        cases.append(CaseResult(**raw, results=results))
    return Run(**data, cases=cases)


def recent_runs(agent: str, suite: str, count: int) -> list[Run]:
    """The `count` most recent saved runs of one agent + suite, oldest first."""
    found = sorted((paths.OUTPUTS_DIR / "runs").glob(f"*_{agent}_{suite}/results.json"))[-max(count, 1):]
    if not found:
        raise FileNotFoundError(f"No saved runs for {agent}/{suite} in {paths.OUTPUTS_DIR / 'runs'}")
    return [load_run(str(p)) for p in found]
