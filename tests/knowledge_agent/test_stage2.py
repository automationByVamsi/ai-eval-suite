"""
Stage 2 — Anchor Node Identification (knowledge_agent only)

Contract → tests/knowledge_agent/stage2_contract.py
Parse    → src/parsers/knowledge_agent/stage2.py
Judge defs → configs/metrics/knowledge_agent/catalog.yaml
Judge suite → configs/evaluations/knowledge_agent/stage2_anchor_node.yaml

Run:   pytest tests/knowledge_agent/test_stage2.py -v -s
View:  streamlit run scripts/dashboard_app.py
"""

import os

import pytest

from tests.knowledge_agent import stage2_contract as contract
from tests.knowledge_agent.base import KnowledgeAgentTest


class TestStage2AnchorNode(KnowledgeAgentTest):
    tag = "sanity"

    @pytest.fixture(autouse=True)
    def setup(self):
        self._cases = self.load_cases()
        self.ensure_traces(list(self._cases.values()))

    @pytest.mark.parametrize("test_case_id", ["TC_001", "TC_002"])
    def test_stage2(self, test_case_id: str):
        case = self._cases[test_case_id]

        # --- Arrange ---
        raw = self.load_trace(test_case_id)
        parsed = self.parse_stage2(raw)

        # --- Assert: Layer 1 deterministic (+ golden accuracy when labelled) ---
        det_results = contract.run_deterministic(parsed, expected=case.expected)
        failed = [r for r in det_results if not r.passed]
        assert not failed, [(r.name, r.reason) for r in failed]

        # --- Act: Layer 2 judges ---
        response = self.build_stage2_response(parsed)
        judge_results = self.run_stage_judges(
            case, response, contract.JUDGE_METRICS, stage=contract.STAGE
        )

        # --- Publish ---
        self.publish(
            eval_name=contract.STAGE,
            test_case=case,
            question=parsed.question,
            answer=parsed.answer,
            context=parsed.context,
            latency_ms=parsed.latency_ms,
            deterministic_results=det_results,
            metric_results=judge_results,
            result_fields={
                "anchor_page_id": parsed.anchor_page_id,
                "selection_method": parsed.selection_method,
                "selection_path": parsed.selection_path,
                "candidate_page_ids": parsed.candidate_page_ids,
                "rewritten_query": parsed.rewritten_query,
            },
        )

        if os.environ.get("RUN_JUDGE_ASSERT") == "1":
            judge_failed = [r for r in judge_results if not r.passed]
            assert not judge_failed, [(r.name, r.reason) for r in judge_failed]
