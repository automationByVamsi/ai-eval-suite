"""
What a result looks like, and how a run is saved and printed.

Every check and every judge produces one `Result` with a status:
    pass  | fail  | skip (the case doesn't have the data this needs) | error (couldn't run)

A case passes when nothing failed and nothing errored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from evalkit.config import OUTPUTS_DIR

PASS, FAIL, SKIP, ERROR = "pass", "fail", "skip", "error"


@dataclass
class Result:
    name: str
    kind: str                    # "check" (deterministic) or "judge" (LLM)
    status: str
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    engine: str = ""             # judges only: "pegasus" or "deepeval"


def check(name: str, passed: bool, reason_if_failed: str = "") -> Result:
    """A deterministic check. Use this in your agent's parser.py."""
    return Result(name=name, kind="check", status=PASS if passed else FAIL,
                  reason="" if passed else reason_if_failed)


@dataclass
class CaseResult:
    case_id: str
    rep: int = 0
    question: str = ""
    answer: str = ""
    expected_answer: str = ""
    latency_ms: float | None = None
    trace: str = ""
    error: str = ""
    results: list[Result] = field(default_factory=list)

    @property
    def status(self) -> str:
        statuses = {r.status for r in self.results}
        if self.error or ERROR in statuses:
            return ERROR
        return FAIL if FAIL in statuses else PASS


@dataclass
class Run:
    agent: str
    suite: str
    build: str = ""
    reps: int = 1
    offline: bool = False
    run_id: str = ""
    started_at: str = ""
    cases: list[CaseResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now().isoformat(timespec="seconds")
        if not self.run_id:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.run_id = f"{stamp}_{self.agent}_{self.suite}"

    @property
    def folder(self) -> Path:
        return OUTPUTS_DIR / "runs" / self.run_id

    @property
    def passed(self) -> bool:
        return all(c.status == PASS for c in self.cases)

    def save(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / "results.json"
        data = asdict(self)
        for case, raw in zip(self.cases, data["cases"], strict=True):
            raw["status"] = case.status
        path.write_text(json.dumps(data, indent=2, default=str))
        return path


def load_run(ref: str, agent: str | None = None, suite: str | None = None) -> Run:
    """Load a saved run by folder name/path, or 'latest' (optionally for one agent + suite)."""
    if ref == "latest":
        runs = sorted((OUTPUTS_DIR / "runs").glob("*/results.json"), reverse=True)
        suffix = f"_{agent}_{suite}" if agent and suite else ""
        runs = [p for p in runs if p.parent.name.endswith(suffix)]
        if not runs:
            raise FileNotFoundError(f"No saved runs{' for ' + agent + '/' + suite if suffix else ''}")
        path = runs[0]
    else:
        path = Path(ref)
        if not path.exists():
            path = OUTPUTS_DIR / "runs" / ref
        if path.is_dir():
            path = path / "results.json"
    data = json.loads(path.read_text())
    cases = []
    for raw in data.pop("cases"):
        raw.pop("status", None)
        results = [Result(**r) for r in raw.pop("results")]
        cases.append(CaseResult(**raw, results=results))
    return Run(**data, cases=cases)


def print_run(run: Run) -> None:
    """Console report: one line per case, reasons for anything that failed."""
    icon = {PASS: "PASS ", FAIL: "FAIL ", ERROR: "ERROR"}
    print(f"\n{run.agent} / {run.suite}" + (f"  build={run.build}" if run.build else ""))
    print("-" * 72)
    for case in run.cases:
        rep = f" (rep {case.rep + 1})" if run.reps > 1 else ""
        skipped = sum(r.status == SKIP for r in case.results)
        note = f"  [{skipped} skipped]" if skipped else ""
        print(f"{icon[case.status]} {case.case_id}{rep}{note}")
        if case.error:
            print(f"        {case.error}")
        for r in case.results:
            if r.status in (FAIL, ERROR):
                score = f" score={r.score:.2f}/{r.threshold}" if r.score is not None else ""
                print(f"        {r.status.upper()} {r.kind}:{r.name}{score} {r.reason}".rstrip())
    counts = {s: sum(c.status == s for c in run.cases) for s in (PASS, FAIL, ERROR)}
    print("-" * 72)
    print(f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[ERROR]} errors"
          f"  ->  {run.folder / 'results.json'}\n")
