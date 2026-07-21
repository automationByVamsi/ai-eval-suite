"""
Demo E2E — fact_find_workflow eval packages → dashboard.

Packages: gate_validation, summary_vs_aggregate.

Run:
    pytest tests/fact_find_workflow/test_demo_e2e.py -v -s
    make demo-ff-e2e
"""

from __future__ import annotations

import os
from typing import Any, Callable

import pytest

from src.models.evaluation_result import CaseEvaluationResult
from tests.fact_find_workflow import gate_validation_contract, summary_vs_aggregate_contract
from tests.fact_find_workflow.base import FactFindWorkflowTest

StageFn = Callable[[FactFindWorkflowTest, Any, Any], tuple[list, list, dict]]


def _run_gate(self: FactFindWorkflowTest, case, raw) -> tuple[list, list, dict]:
    parsed = self.parse_gate_validation(raw)
    det = gate_validation_contract.run_deterministic(parsed, expected=case.expected)
    response = self.build_gate_response(parsed)
    judges = self.run_stage_judges(
        case, response, gate_validation_contract.JUDGE_METRICS, stage=gate_validation_contract.STAGE
    )
    return det, judges, {
        "stage": gate_validation_contract.STAGE,
        "question": parsed.complaint_ref,
        "answer": parsed.answer,
        "context": parsed.context,
        "latency_ms": parsed.latency_ms,
        "result_fields": {
            "complaint_ref": parsed.complaint_ref,
            "validation_failed": parsed.validation_failed,
            "path": case.expected.get("path"),
        },
    }


def _run_summary(self: FactFindWorkflowTest, case, raw) -> tuple[list, list, dict]:
    parsed = self.parse_summary_vs_aggregate(raw)
    det = summary_vs_aggregate_contract.run_deterministic(parsed, expected=case.expected)
    response = self.build_summary_response(parsed)
    path = case.expected.get("path", parsed.path)
    judge_names = (
        summary_vs_aggregate_contract.JUDGE_METRICS_INVALID
        if path == "invalid_complaint"
        else list(summary_vs_aggregate_contract.JUDGE_METRICS)
    )
    if not parsed.tools_called:
        judge_names = [
            n for n in judge_names if n not in summary_vs_aggregate_contract.MCP_OR_TOOL_METRICS
        ]
    judges = (
        self.run_stage_judges(case, response, judge_names, stage=summary_vs_aggregate_contract.STAGE)
        if judge_names
        else []
    )
    return det, judges, {
        "stage": summary_vs_aggregate_contract.STAGE,
        "question": parsed.complaint_ref,
        "answer": parsed.answer,
        "context": parsed.context,
        "latency_ms": parsed.latency_ms,
        "result_fields": {
            "complaint_ref": parsed.complaint_ref,
            "path": path,
            "party_id": (parsed.expected_facts or {}).get("party_id"),
        },
    }


STAGES: list[tuple[str, StageFn]] = [
    ("gate_validation", _run_gate),
    ("summary_vs_aggregate", _run_summary),
]


class TestFactFindWorkflowDemoE2E(FactFindWorkflowTest):
    tag = "sanity"

    @pytest.fixture(autouse=True)
    def setup(self):
        self._cases = self.load_cases()
        self.ensure_traces(list(self._cases.values()))

    def test_all_stages_end_to_end(self):
        failures: list[str] = []

        for test_case_id, case in sorted(self._cases.items()):
            raw = self.load_trace(test_case_id)
            stage_results: list[CaseEvaluationResult] = []
            case_latency = 0.0

            for stage_name, run_fn in STAGES:
                det_results, judge_results, meta = run_fn(self, case, raw)
                stage_result = self.publish(
                    eval_name=meta["stage"],
                    test_case=case,
                    question=meta["question"],
                    answer=meta["answer"],
                    context=meta["context"],
                    latency_ms=meta["latency_ms"],
                    deterministic_results=det_results,
                    metric_results=judge_results,
                    result_fields=meta["result_fields"],
                )
                stage_results.append(stage_result)
                if meta["latency_ms"]:
                    case_latency += meta["latency_ms"]

                det_failed = [r.name for r in det_results if not r.passed]
                if det_failed:
                    failures.append(f"{test_case_id}/{stage_name} det: {det_failed}")

                if os.environ.get("RUN_JUDGE_ASSERT") == "1":
                    judge_failed = [r.name for r in judge_results if not r.passed]
                    if judge_failed:
                        failures.append(f"{test_case_id}/{stage_name} judge: {judge_failed}")

            self.publish_e2e(
                test_case=case,
                stages=stage_results,
                question=stage_results[0].question if stage_results else "",
                latency_ms=case_latency or None,
            )

        assert not failures, failures
