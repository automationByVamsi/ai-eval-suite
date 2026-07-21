"""
FactFindWorkflowTest — fact_find_workflow specific helpers.

Eval packages (not KA-style pipeline stages):
  gate_validation       — complaint ref accept/reject
  summary_vs_aggregate  — UI summary vs aggregated payload ground truth
"""

from __future__ import annotations

from typing import Any

from src.core.config import load_eval_config
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.parsers.fact_find_workflow.gate_validation import (
    GateValidationParsed,
    parse as parse_gate_validation,
)
from src.parsers.fact_find_workflow.mcp_catalog import (
    default_factfind_mcp_servers,
    extract_mcp_tools_called,
)
from src.parsers.fact_find_workflow.summary_vs_aggregate import (
    SummaryVsAggregateParsed,
    parse as parse_summary_vs_aggregate,
)
from src.runners.factories import MetricFactory
from tests.base_agent_test import BaseAgentTest


class FactFindWorkflowTest(BaseAgentTest):
    profile: str = "fact_find_workflow"

    def parse_gate_validation(self, raw_trace: dict[str, Any]) -> GateValidationParsed:
        return parse_gate_validation(raw_trace)

    def parse_summary_vs_aggregate(self, raw_trace: dict[str, Any]) -> SummaryVsAggregateParsed:
        expected = (raw_trace.get("test_case") or {}).get("expected") or {}
        return parse_summary_vs_aggregate(
            raw_trace,
            aggregated_payload_path=expected.get("aggregated_payload_path"),
        )

    def build_gate_response(self, parsed: GateValidationParsed, **extra_metadata: Any) -> AgentResponse:
        metadata = {
            "complaint_ref": parsed.complaint_ref,
            "validation_failed": parsed.validation_failed,
            "successful_run": parsed.successful_run,
        }
        metadata.update(extra_metadata)
        return AgentResponse(
            answer=parsed.answer,
            context=parsed.context,
            events=parsed.events,
            metadata=metadata,
            session_id=parsed.session_id,
            latency_ms=parsed.latency_ms,
        )

    def build_summary_response(
        self, parsed: SummaryVsAggregateParsed, **extra_metadata: Any
    ) -> AgentResponse:
        # source_document = concatenated aggregate context for SummarizationMetric
        source_document = "\n\n".join(parsed.context) if parsed.context else ""
        mcp_tools = extract_mcp_tools_called(
            {"raw_events": parsed.events, "agentOutput": parsed.answer}
        )
        metadata = {
            "complaint_ref": parsed.complaint_ref,
            "path": parsed.path,
            "expected_facts": parsed.expected_facts,
            "retrieval_context": parsed.context,
            "ground_truth_context": parsed.context,  # HallucinationMetric uses context=
            "source_document": source_document,
            "tools_called": parsed.tools_called,
            "expected_tools": parsed.expected_tools,
            "mcp_servers": default_factfind_mcp_servers(),
            "mcp_tools_called": mcp_tools,
        }
        metadata.update(extra_metadata)
        return AgentResponse(
            answer=parsed.answer,
            context=parsed.context,
            events=parsed.events,
            metadata=metadata,
            session_id=parsed.session_id,
            latency_ms=parsed.latency_ms,
        )

    def run_stage_judges(
        self,
        test_case: TestCase,
        response: AgentResponse,
        metric_names: list[str],
        stage: str,
    ) -> list[MetricResult]:
        factory = MetricFactory(self.cortex_config)
        stage_config = load_eval_config(self.profile, stage)
        by_name = {m["name"]: m for m in stage_config.get("judge_metrics", [])}
        missing = [n for n in metric_names if n not in by_name]
        assert not missing, f"Unknown metrics: {missing}. Available: {sorted(by_name)}"
        return [factory.create(by_name[n]).evaluate(test_case, response) for n in metric_names]
