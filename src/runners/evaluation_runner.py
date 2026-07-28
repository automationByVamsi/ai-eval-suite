"""
Core end-to-end flow behind `python -m src.main`: load test cases, live ADK
invoke, score with metrics, write per-case results plus a summary.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.clients.adk_client import invoke_agent
from src.core.config import agent_metrics_profile, has_metric_catalog, load_metric_catalog, resolve_suite_metrics
from src.models.evaluation_result import EvaluationResult
from src.models.test_case import TestCase
from src.reporting.persist import publish_suite_result
from src.runners.factories import MetricFactory


class EvaluationRunner:
    """Run live agent evals from JSON cases and write result files."""
    def __init__(
        self,
        metric_factory: MetricFactory,
        *,
        agents_path: str = "configs/agents.yaml",
        save_dir: Path | None = None,
    ):
        """Store shared config for repeated test-case runs."""
        self.metric_factory = metric_factory
        self.agents_path = agents_path
        self.save_dir = save_dir

    def run_test_case(self, test_case: TestCase) -> EvaluationResult:
        """Invoke the agent for one case, score it, and return the result."""
        try:
            payload = {**test_case.input, "_test_case_id": test_case.test_case_id}
            response = invoke_agent(
                test_case.agent_name,
                payload,
                save_dir=self.save_dir,
                agents_path=self.agents_path,
            )
        except Exception as exc:  # noqa: BLE001
            return EvaluationResult(
                test_case_id=test_case.test_case_id,
                agent_name=test_case.agent_name,
                passed=False,
                error=str(exc),
            )

        metric_configs = self._resolve_metric_configs(test_case)
        metric_results = [
            self.metric_factory.create(cfg).evaluate(test_case, response) for cfg in metric_configs
        ]

        # Blind path: same Streamlit dashboard as evaluate()
        if os.environ.get("DASHBOARD_DISABLE") != "1":
            publish_suite_result(
                agent_name=test_case.agent_name,
                suite=test_case.suite or "run",
                case={
                    "test_case_id": test_case.test_case_id,
                    "input": test_case.input,
                    "expected": test_case.expected,
                },
                response=response,
                judges=metric_results,
            )

        return EvaluationResult(
            test_case_id=test_case.test_case_id,
            agent_name=test_case.agent_name,
            passed=all(m.passed for m in metric_results),
            metric_results=metric_results,
        )

    def _resolve_metric_configs(self, test_case: TestCase) -> list[dict]:
        """Resolve the metric configs that should run for this case."""
        profile = agent_metrics_profile(test_case.agent_name, path=self.agents_path)

        if test_case.suite:
            pool = resolve_suite_metrics(profile, test_case.suite)
        else:
            pool = self.metric_factory.load_base_metrics(profile)

        if not test_case.metrics:
            return pool

        by_name = {m["name"]: m for m in pool}
        if has_metric_catalog(profile):
            catalog = load_metric_catalog(profile)
            for name, cfg in catalog.items():
                by_name.setdefault(name, cfg)

        configs = []
        for override in test_case.metrics:
            cfg = dict(by_name.get(override.name, {"name": override.name}))
            if override.threshold is not None:
                cfg["threshold"] = override.threshold
            if override.type is not None:
                cfg["type"] = override.type
            configs.append(cfg)
        return configs

    def run_all(self, test_case_paths: list[str], output_dir: str) -> list[EvaluationResult]:
        """Run every requested test case and write per-case outputs."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        results = []
        for path in test_case_paths:
            test_case = TestCase.from_json_file(path)
            result = self.run_test_case(test_case)
            result.print_summary()
            (output_path / f"{test_case.test_case_id}.json").write_text(
                result.model_dump_json(indent=2)
            )
            results.append(result)

        summary = {
            "total": len(results),
            "passed": sum(r.passed for r in results),
            "failed": sum(not r.passed for r in results),
            "results": [r.model_dump() for r in results],
        }
        (output_path / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        return results
