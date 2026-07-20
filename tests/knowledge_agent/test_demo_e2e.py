"""
Demo E2E — run every available knowledge_agent stage, publish to dashboard.

Publishes:
  1. Stage-level files (unchanged) — <agent>/<stage>__<id>.json
  2. E2E rollup per case         — <agent>/e2e__<id>.json

Stages today: stage1 (query rewrite + search), stage2 (anchor node).
Add a new stage = append one entry to STAGES below.

Run:
    pytest tests/knowledge_agent/test_demo_e2e.py -v -s
    make demo-e2e

Then:
    make dashboard
    → sidebar: View = "By test case (e2e)"
"""

from __future__ import annotations

import os
from typing import Any, Callable

import pytest

from src.models.evaluation_result import CaseEvaluationResult
from tests.knowledge_agent import stage1_contract, stage2_contract
from tests.knowledge_agent.base import KnowledgeAgentTest

# ---------------------------------------------------------------------------
# Registry of stages — append here when stage3+ lands
# ---------------------------------------------------------------------------

StageFn = Callable[[KnowledgeAgentTest, dict[str, Any], Any], tuple[list, list, dict]]


def _run_stage1(self: KnowledgeAgentTest, case, raw) -> tuple[list, list, dict]:
    parsed = self.parse_stage1(raw)
    det = stage1_contract.run_deterministic(parsed)
    response = self.build_response(parsed)
    judges = self.run_stage_judges(
        case, response, stage1_contract.JUDGE_METRICS, stage=stage1_contract.STAGE
    )
    fields = {
        "rewritten_query": parsed.rewritten_query,
        "artifact_id": parsed.artifact_id,
        "result_count": parsed.result_count,
        "deduplicated_page_ids": parsed.deduplicated_page_ids_count,
        "business_area": parsed.business_area,
    }
    return det, judges, {
        "stage": stage1_contract.STAGE,
        "question": parsed.question,
        "answer": parsed.answer,
        "context": parsed.context,
        "latency_ms": parsed.latency_ms,
        "result_fields": fields,
    }


def _run_stage2(self: KnowledgeAgentTest, case, raw) -> tuple[list, list, dict]:
    parsed = self.parse_stage2(raw)
    det = stage2_contract.run_deterministic(parsed, expected=case.expected)
    response = self.build_stage2_response(parsed)
    judges = self.run_stage_judges(
        case, response, stage2_contract.JUDGE_METRICS, stage=stage2_contract.STAGE
    )
    fields = {
        "anchor_page_id": parsed.anchor_page_id,
        "selection_method": parsed.selection_method,
        "selection_path": parsed.selection_path,
        "candidate_page_ids": parsed.candidate_page_ids,
        "rewritten_query": parsed.rewritten_query,
    }
    return det, judges, {
        "stage": stage2_contract.STAGE,
        "question": parsed.question,
        "answer": parsed.answer,
        "context": parsed.context,
        "latency_ms": parsed.latency_ms,
        "result_fields": fields,
    }


STAGES: list[tuple[str, StageFn]] = [
    ("stage1_query_rewrite", _run_stage1),
    ("stage2_anchor_node", _run_stage2),
]


class TestKnowledgeAgentDemoE2E(KnowledgeAgentTest):
    """One walkthrough: every sanity case × every registered stage → dashboard."""

    tag = "sanity"

    @pytest.fixture(autouse=True)
    def setup(self):
        self._cases = self.load_cases()
        self.ensure_traces(list(self._cases.values()))

    def test_all_stages_end_to_end(self):
        print(f"\n=== Demo E2E: agent={self.profile} tag={self.tag} ===")
        print(f"Stages: {[name for name, _ in STAGES]}")
        print(f"Cases:  {list(self._cases)}")

        failures: list[str] = []

        for test_case_id, case in sorted(self._cases.items()):
            raw = self.load_trace(test_case_id)
            print(f"\n--- {test_case_id} ---")

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
                judge_failed = [r.name for r in judge_results if not r.passed]
                det_ok = len(det_results) - len(det_failed)
                judge_ok = len(judge_results) - len(judge_failed)
                status = "PASS" if not det_failed else "FAIL"
                print(
                    f"  [{status}] {stage_name}: "
                    f"deterministic {det_ok}/{len(det_results)}, "
                    f"judge {judge_ok}/{len(judge_results)}"
                )

                if det_failed:
                    failures.append(f"{test_case_id}/{stage_name} det: {det_failed}")

                if os.environ.get("RUN_JUDGE_ASSERT") == "1" and judge_failed:
                    failures.append(f"{test_case_id}/{stage_name} judge: {judge_failed}")

            e2e_path = self.publish_e2e(
                test_case=case,
                stages=stage_results,
                question=stage_results[0].question if stage_results else "",
                latency_ms=case_latency or None,
            )
            print(f"  [e2e rollup] -> {e2e_path}")

        print(f"\n=== Done — view with: make dashboard (By test case) ===\n")
        assert not failures, failures
