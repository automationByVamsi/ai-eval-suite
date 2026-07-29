"""
Run suite judges for any agent.

  evaluate(agent_name, suite, case, response) → EvalResult

Catalog `mode:` selects scoring backend:
  - deepeval (default) → existing MetricFactory / DeepEval path
  - pegasus | pegasus_ragas | pegasus_deepeval → lbg-pegasus (faithfulness / relevancy / correctness)

Always publishes to outputs/dashboard (Streamlit) unless publish=False or
DASHBOARD_DISABLE=1. Callers do not need to touch persist themselves.

Suite YAML lists judge names only; catalog defines how they run.
Deterministic / stage parsing stays in the agent pack.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.config import agent_metrics_profile, resolve_suite_metrics
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.reporting.persist import publish_suite_result
from src.runners.factories import MetricFactory
from src.runners.pegasus_judge import run_pegasus_metric


@dataclass
class CheckResult:
    """One judge outcome in the lightweight evaluate() flow."""
    name: str
    passed: bool
    reason: str = ""
    score: float | None = None
    threshold: float | None = None


@dataclass
class EvalResult:
    """Judge results for one case and suite run."""
    agent_name: str
    suite: str
    test_case_id: str
    judges: list[CheckResult] = field(default_factory=list)
    dashboard_path: Path | None = None

    @property
    def passed(self) -> bool:
        """Return whether every judge passed."""
        return all(j.passed for j in self.judges)

    @property
    def failed(self) -> list[CheckResult]:
        """Return only the judges that failed."""
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
    publish: bool | None = None,
) -> EvalResult:
    """
    Resolve metrics_profile + suite → catalog defs → run each judge on response.

    By default writes CaseEvaluationResult under outputs/dashboard for Streamlit.
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
        mode = str(cfg.get("mode") or "deepeval").strip().lower()
        if mode.startswith("pegasus"):
            result = run_pegasus_metric(
                cfg,
                test_case,
                response,
                cortex_client=factory._cortex_client,
            )
        else:
            result = factory.create(cfg).evaluate(test_case, response)
        judges.append(
            CheckResult(
                name=result.name,
                passed=result.passed,
                reason=result.reason or "",
                score=result.score,
                threshold=result.threshold,
            )
        )

    eval_result = EvalResult(
        agent_name=agent_name,
        suite=suite,
        test_case_id=test_case.test_case_id,
        judges=judges,
    )

    do_publish = publish if publish is not None else os.environ.get("DASHBOARD_DISABLE") != "1"
    if do_publish:
        eval_result.dashboard_path = publish_suite_result(
            agent_name=agent_name,
            suite=suite,
            case=case,
            response=response,
            judges=judges,
        )

    return eval_result


def _should_run_metric(cfg: dict[str, Any], test_case: TestCase) -> bool:
    """Skip judges that need optional expected data when it is absent."""
    name = cfg.get("name")
    mtype = cfg.get("type", name)
    if mtype == "keyword_match" or name == "keyword_match":
        keywords = test_case.expected.get(cfg.get("keywords_source") or "keywords")
        return bool(keywords)
    if (
        mtype in {"correctness", "answer_correctness"}
        or name in {"correctness", "correctness_pegasus"}
    ):
        src = cfg.get("expected_source") or "expected_answer"
        golden = test_case.expected.get(src) or test_case.expected.get("answer")
        return bool(golden and str(golden).strip())
    return True
