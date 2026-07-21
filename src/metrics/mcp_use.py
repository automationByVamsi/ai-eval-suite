"""
DeepEval MCPUseMetric adapter — did the agent use the right MCP primitives?

Valid for Fact Find success path when mcp_servers + tools_called / mcp_tools_called
are present. Requires LLMTestCase.mcp_servers.
"""

from __future__ import annotations

from typing import Any, Optional

from deepeval.metrics import MCPUseMetric
from deepeval.test_case import LLMTestCase
from deepeval.test_case.mcp import MCPServer, MCPToolCall

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.parsers.fact_find_workflow.mcp_catalog import (
    default_factfind_mcp_servers,
    mcp_tools_from_tool_calls,
)


@METRIC_REGISTRY.register("mcp_use")
class MCPUseMetricAdapter(DeepEvalMetric):
    def __init__(
        self,
        *args,
        mcp_servers_source: str = "mcp_servers",
        mcp_tools_called_source: str = "mcp_tools_called",
        tools_called_source: str = "tools_called",
        **kwargs,
    ):
        super().__init__(
            *args,
            tools_called_source=tools_called_source,
            **kwargs,
        )
        self.mcp_servers_source = mcp_servers_source
        self.mcp_tools_called_source = mcp_tools_called_source

    def build_deepeval_metric(self):
        return MCPUseMetric(
            threshold=self.threshold,
            model=self.cortex_llm,
            include_reason=True,
            async_mode=False,
        )

    def build_llm_test_case(self, test_case: TestCase, response: AgentResponse) -> LLMTestCase:
        base = super().build_llm_test_case(test_case, response)
        servers = resolve_field(self.mcp_servers_source, test_case, response)
        if not servers:
            servers = default_factfind_mcp_servers()
        if not isinstance(servers, list) or not all(isinstance(s, MCPServer) for s in servers):
            servers = default_factfind_mcp_servers()

        mcp_tools = resolve_field(self.mcp_tools_called_source, test_case, response)
        if not mcp_tools:
            mcp_tools = mcp_tools_from_tool_calls(base.tools_called)
        if mcp_tools and isinstance(mcp_tools[0], dict):
            mcp_tools = [
                MCPToolCall(
                    name=str(t.get("name")),
                    args=t.get("args") or {},
                    result=t.get("result") or {},
                )
                for t in mcp_tools
                if t.get("name")
            ]

        return LLMTestCase(
            input=base.input,
            actual_output=base.actual_output,
            retrieval_context=base.retrieval_context,
            expected_output=base.expected_output,
            tools_called=base.tools_called,
            expected_tools=base.expected_tools,
            mcp_servers=servers,
            mcp_tools_called=mcp_tools or None,
        )

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        llm_case = self.build_llm_test_case(test_case, response)
        if not llm_case.mcp_tools_called and not llm_case.tools_called:
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason="Skipped: no mcp_tools_called / tools_called on the response (need live ADK MCP/tool events).",
            )
        try:
            metric = self.build_deepeval_metric()
            metric.measure(llm_case)
            score = metric.score or 0.0
            return MetricResult(
                name=self.name,
                score=score,
                threshold=self.threshold,
                passed=score >= self.threshold,
                reason=metric.reason or "",
            )
        except Exception as exc:  # noqa: BLE001
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason=f"Metric errored: {exc}",
            )
