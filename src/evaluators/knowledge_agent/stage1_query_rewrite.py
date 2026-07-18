"""Stage 1 of the knowledge_agent pipeline: did the query-rewrite step run and carry into state?"""

from typing import Any

from src.evaluators.base_stage_evaluator import BaseStageEvaluator
from src.models.evaluation_result import DeterministicCheckResult
from src.parsers.knowledge_agent.models import Stage1Trace
from src.parsers.knowledge_agent.parser import parse_stage1


class Stage1QueryRewriteEvaluator(BaseStageEvaluator):
    stage_name = "stage1_query_rewrite"
    agent_profile = "knowledge_agent"

    def parse_trace(self, raw: dict[str, Any]) -> Stage1Trace:
        return parse_stage1(raw)

    def run_deterministic(self, parsed: Stage1Trace) -> list[DeterministicCheckResult]:
        return [
            DeterministicCheckResult(
                name="rewrite_step_ran",
                passed=parsed.rewrite_ran,
                reason="" if parsed.rewrite_ran else "No query_rewrite event found in the trace",
            ),
            DeterministicCheckResult(
                name="rewritten_query_carried_into_state",
                passed=parsed.carried_into_state,
                reason=(
                    ""
                    if parsed.carried_into_state
                    else "state.rewritten_query does not match the query_rewrite event output"
                ),
            ),
        ]

    def get_response_metadata(self, parsed: Stage1Trace) -> dict[str, Any]:
        return {"rewritten_query": parsed.rewritten_query or ""}

    def get_result_fields(self, parsed: Stage1Trace) -> dict[str, Any]:
        return {"question": parsed.question, "rewritten_query": parsed.rewritten_query}
