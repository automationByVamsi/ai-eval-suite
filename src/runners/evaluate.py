"""
Run suite judges (DeepEval / GEval via CORTEX) for any agent.

  evaluate(agent_name, suite, case, response) → EvalResult

- Suite YAML lists judge names only; catalog defines how they run.
- Deterministic / stage parsing is NOT here — that stays in the agent pack
  (e.g. knowledge_agent stage contracts + parsers).

Caller prepares AgentResponse (answer, context, metadata field sources).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.config import agent_metrics_profile, resolve_suite_metrics
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.runners.factories import MetricFactory


@dataclass
class CheckResult:
    name: str
    passed: bool
    reason: str = ""
    score: float | None = None
    threshold: float | None = None


@dataclass
class EvalResult:
    agent_name: str
    suite: str
    test_case_id: str
    judges: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(j.passed for j in self.judges)

    @property
    def failed(self) -> list[CheckResult]:
        return [j for j in self.judges if not j.passed]


def load_trace(
    response_path: str | Path,
    case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Load saved ADK JSON as { test_case, raw_output }.
    Accepts flat AdkClient saves and wrapped capture traces.
    """
    path = Path(response_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")

    case = case or {}
    case_block = {
        "test_case_id": case.get("test_case_id", path.stem),
        "input": dict(case.get("input") or {}),
        "expected": dict(case.get("expected") or {}),
    }

    if "raw_output" in data and isinstance(data["raw_output"], dict):
        wrapped = dict(data)
        existing = wrapped.get("test_case") if isinstance(wrapped.get("test_case"), dict) else {}
        wrapped["test_case"] = {
            **existing,
            **{k: v for k, v in case_block.items() if v},
            "input": case_block["input"] or existing.get("input") or {},
            "expected": case_block["expected"] or existing.get("expected") or {},
        }
        return wrapped

    return {"test_case": case_block, "raw_output": data}


def evaluate(
    agent_name: str,
    suite: str,
    case: dict[str, Any],
    response: AgentResponse,
    *,
    agents_path: str | Path = "configs/agents.yaml",
    cortex_config: str = "configs/cortex.yaml",
) -> EvalResult:
    """
    Resolve metrics_profile + suite → catalog defs → run each judge on response.
    """
    profile = agent_metrics_profile(agent_name, path=agents_path)
    metric_cfgs = resolve_suite_metrics(profile, suite)

    test_case = TestCase(
        test_case_id=str(case.get("test_case_id") or "case"),
        agent_name=agent_name,
        description=str(case.get("description") or ""),
        input=dict(case.get("input") or {}),
        expected=dict(case.get("expected") or {}),
    )

    factory = MetricFactory(cortex_config)
    judges: list[CheckResult] = []
    for cfg in metric_cfgs:
        if not _should_run_metric(cfg, test_case):
            continue
        result: MetricResult = factory.create(cfg).evaluate(test_case, response)
        judges.append(
            CheckResult(
                name=result.name,
                passed=result.passed,
                reason=result.reason or "",
                score=result.score,
                threshold=result.threshold,
            )
        )

    return EvalResult(
        agent_name=agent_name,
        suite=suite,
        test_case_id=test_case.test_case_id,
        judges=judges,
    )


def _should_run_metric(cfg: dict[str, Any], test_case: TestCase) -> bool:
    """Skip judges that need optional expected data when it is absent."""
    name = cfg.get("name")
    mtype = cfg.get("type", name)
    if mtype == "keyword_match" or name == "keyword_match":
        keywords = test_case.expected.get(cfg.get("keywords_source") or "keywords")
        return bool(keywords)
    return True
