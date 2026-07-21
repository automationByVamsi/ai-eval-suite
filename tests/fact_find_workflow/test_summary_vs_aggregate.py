"""
Summary vs aggregate — UI summary quality vs aggregated payload (fact_find_workflow)

Run:   pytest tests/fact_find_workflow/test_summary_vs_aggregate.py -v -s
"""

import os

import pytest

from tests.fact_find_workflow import summary_vs_aggregate_contract as contract
from tests.fact_find_workflow.base import FactFindWorkflowTest


class TestSummaryVsAggregate(FactFindWorkflowTest):
    tag = "sanity"

    @pytest.fixture(autouse=True)
    def setup(self):
        self._cases = self.load_cases()
        self.ensure_traces(list(self._cases.values()))

    @pytest.mark.parametrize("test_case_id", ["TC_001", "TC_002"])
    def test_summary_vs_aggregate(self, test_case_id: str):
        case = self._cases[test_case_id]
        raw = self.load_trace(test_case_id)
        parsed = self.parse_summary_vs_aggregate(raw)

        det_results = contract.run_deterministic(parsed, expected=case.expected)
        failed = [r for r in det_results if not r.passed]
        assert not failed, [(r.name, r.reason) for r in failed]

        response = self.build_summary_response(parsed)
        path = case.expected.get("path", parsed.path)
        judge_names = (
            contract.JUDGE_METRICS_INVALID
            if path == "invalid_complaint"
            else list(contract.JUDGE_METRICS)
        )
        # Skip MCP/tool metrics when the trace has no tool events yet (replay fixtures).
        if not parsed.tools_called:
            judge_names = [n for n in judge_names if n not in contract.MCP_OR_TOOL_METRICS]

        judge_results = (
            self.run_stage_judges(case, response, judge_names, stage=contract.STAGE)
            if judge_names
            else []
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
                "path": path,
                "party_id": (parsed.expected_facts or {}).get("party_id"),
                "tools_called": [t.name for t in (parsed.tools_called or [])],
                "sections": {
                    "customer_profile": parsed.has_customer_profile_section,
                    "support_needs": parsed.has_support_needs_section,
                    "account_holdings": parsed.has_account_holdings_section,
                    "related_parties": parsed.has_related_parties_section,
                    "contact_notes": parsed.has_contact_notes_section,
                },
                "fidelity": {
                    "support_needs_hits": parsed.support_needs_hit_count,
                    "support_needs_total": parsed.support_needs_total,
                    "trusted_honest": parsed.mentions_no_trusted_party
                    and not parsed.invents_trusted_party,
                    "complaint_account_marked": parsed.marks_complaint_associated_account,
                },
            },
        )

        if os.environ.get("RUN_JUDGE_ASSERT") == "1":
            judge_failed = [r for r in judge_results if not r.passed]
            assert not judge_failed, [(r.name, r.reason) for r in judge_failed]
