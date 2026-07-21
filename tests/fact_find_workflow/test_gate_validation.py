"""
Gate validation — complaint ref accept/reject (fact_find_workflow)

Run:   pytest tests/fact_find_workflow/test_gate_validation.py -v -s
"""

import os

import pytest

from tests.fact_find_workflow import gate_validation_contract as contract
from tests.fact_find_workflow.base import FactFindWorkflowTest


class TestGateValidation(FactFindWorkflowTest):
    tag = "sanity"

    @pytest.fixture(autouse=True)
    def setup(self):
        self._cases = self.load_cases()
        self.ensure_traces(list(self._cases.values()))

    @pytest.mark.parametrize("test_case_id", ["TC_001", "TC_002"])
    def test_gate_validation(self, test_case_id: str):
        case = self._cases[test_case_id]
        raw = self.load_trace(test_case_id)
        parsed = self.parse_gate_validation(raw)

        det_results = contract.run_deterministic(parsed, expected=case.expected)
        failed = [r for r in det_results if not r.passed]
        assert not failed, [(r.name, r.reason) for r in failed]

        response = self.build_gate_response(parsed)
        judge_results = self.run_stage_judges(
            case, response, contract.JUDGE_METRICS, stage=contract.STAGE
        )

        self.publish(
            eval_name=contract.STAGE,
            test_case=case,
            question=parsed.complaint_ref,
            answer=parsed.answer,
            context=parsed.context,
            latency_ms=parsed.latency_ms,
            deterministic_results=det_results,
            metric_results=judge_results,
            result_fields={
                "complaint_ref": parsed.complaint_ref,
                "validation_failed": parsed.validation_failed,
                "successful_run": parsed.successful_run,
                "path": case.expected.get("path"),
            },
        )

        if os.environ.get("RUN_JUDGE_ASSERT") == "1":
            judge_failed = [r for r in judge_results if not r.passed]
            assert not judge_failed, [(r.name, r.reason) for r in judge_failed]
