"""
DeepEval MCPTaskCompletionMetric adapter.

Native metric is conversational (ConversationalTestCase). For Fact Find we
adapt a single-turn complaint_ref → summary into a 2-turn conversation so
we can score whether the MCP-backed task was completed.
"""

from __future__ import annotations

from deepeval.metrics import MCPTaskCompletionMetric
from deepeval.test_case import ConversationalTestCase, Turn
from deepeval.test_case.mcp import MCPServer

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import BaseMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase
from src.parsers.fact_find_workflow.mcp_catalog import (
    default_factfind_mcp_servers,
    mcp_tools_from_tool_calls,
)


@METRIC_REGISTRY.register("mcp_task_completion")
class MCPTaskCompletionMetricAdapter(BaseMetric):
    """
    Did the agent complete the Fact Find task given MCP tool usage?

    Builds:
      Turn(user, complaint_ref) → Turn(assistant, summary, mcp_tools_called)
    """

    def __init__(
        self,
        name: str,
        threshold: float = 0.7,
        cortex_client=None,
        input_source: str = "complaint_ref",
        actual_source: str = "answer",
        mcp_servers_source: str = "mcp_servers",
        mcp_tools_called_source: str = "mcp_tools_called",
        tools_called_source: str = "tools_called",
        expected_outcome: str | None = None,
        **_kwargs,
    ):
        super().__init__(name, threshold)
        from src.clients.cortex_deepeval import CortexDeepEvalLLM

        self.cortex_llm = CortexDeepEvalLLM(cortex_client) if cortex_client else None
        self.input_source = input_source
        self.actual_source = actual_source
        self.mcp_servers_source = mcp_servers_source
        self.mcp_tools_called_source = mcp_tools_called_source
        self.tools_called_source = tools_called_source
        self.expected_outcome = expected_outcome or (
            "Produce a complete Customer FactFind Summary for the complaint "
            "reference using backend MCP tools (ICA, account details, holdings, "
            "contact notes, trusted parties), without inventing data."
        )

    def _build_conversation(
        self, test_case: TestCase, response: AgentResponse
    ) -> ConversationalTestCase:
        user_text = str(resolve_field(self.input_source, test_case, response) or "")
        assistant_text = str(resolve_field(self.actual_source, test_case, response) or "")

        servers = resolve_field(self.mcp_servers_source, test_case, response)
        if not (isinstance(servers, list) and servers and isinstance(servers[0], MCPServer)):
            servers = default_factfind_mcp_servers()

        mcp_tools = resolve_field(self.mcp_tools_called_source, test_case, response)
        if not mcp_tools:
            tools = resolve_field(self.tools_called_source, test_case, response) or []
            mcp_tools = mcp_tools_from_tool_calls(tools)

        turns = [
            Turn(role="user", content=user_text),
            Turn(
                role="assistant",
                content=assistant_text,
                mcp_tools_called=mcp_tools or None,
                tools_called=resolve_field(self.tools_called_source, test_case, response) or None,
            ),
        ]
        return ConversationalTestCase(
            turns=turns,
            scenario="Fact Find Workflow: gather customer facts for a complaint reference via MCP tools and summarise for an advisor.",
            expected_outcome=self.expected_outcome,
            mcp_servers=servers,
            name=test_case.test_case_id,
        )

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        conversation = self._build_conversation(test_case, response)
        assistant = conversation.turns[-1] if conversation.turns else None
        has_tools = bool(
            assistant
            and (assistant.mcp_tools_called or assistant.tools_called)
        )
        if not has_tools:
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason=(
                    "Skipped: no MCP/tool calls on the assistant turn "
                    "(need live ADK MCP/tool events for mcp_task_completion)."
                ),
            )
        try:
            metric = MCPTaskCompletionMetric(
                threshold=self.threshold,
                model=self.cortex_llm,
                include_reason=True,
                async_mode=False,
            )
            metric.measure(conversation)
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
