"""
KnowledgeAgentTest — knowledge_agent specific helpers.

Stage parsers live in src/parsers/knowledge_agent/stageN.py.
This base only wires them into tests + stage judge YAML.
"""

from __future__ import annotations

from typing import Any

from src.core.config import load_eval_config
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.parsers.knowledge_agent.stage1 import Stage1Parsed, parse as parse_stage1
from src.parsers.knowledge_agent.stage2 import Stage2Parsed, parse as parse_stage2
from src.runners.factories import MetricFactory
from tests.base_agent_test import BaseAgentTest


class KnowledgeAgentTest(BaseAgentTest):
    """Parse KA traces + run stage judge metrics from configs/evaluations/knowledge_agent/."""

    profile: str = "knowledge_agent"

    def parse_stage1(self, raw_trace: dict[str, Any]) -> Stage1Parsed:
        return parse_stage1(raw_trace)

    def parse_stage2(self, raw_trace: dict[str, Any]) -> Stage2Parsed:
        return parse_stage2(raw_trace)

    def build_response(self, parsed: Stage1Parsed, **extra_metadata: Any) -> AgentResponse:
        metadata = {
            "rewritten_query": parsed.rewritten_query or "",
            "business_area": parsed.business_area or "",
            "artifact_id": parsed.artifact_id or "",
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

    def build_stage2_response(self, parsed: Stage2Parsed, **extra_metadata: Any) -> AgentResponse:
        metadata = {
            "rewritten_query": parsed.rewritten_query or "",
            "anchor_page_id": parsed.anchor_page_id or "",
            "anchor_page_content": parsed.anchor_page_content or "",
            "selection_method": parsed.selection_method or "",
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
