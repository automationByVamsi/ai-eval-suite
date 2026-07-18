"""
Turns a raw captured knowledge_agent trace (see outputs/traces/knowledge_agent/
for real examples) into the typed Stage1Trace object the stage 1 evaluator
works with. This is the one place that understands the agent's raw event
shape for this stage.
"""

from typing import Any

from src.agents import adk_parser
from src.parsers.knowledge_agent.models import Stage1Trace


def parse_stage1(raw: dict[str, Any]) -> Stage1Trace:
    test_case = raw.get("test_case", {})
    agent_output = raw.get("raw_output", {})

    rewrite_event = adk_parser.find_event_by_author(agent_output, "query_rewrite_agent")
    rewritten_query = adk_parser.event_json(rewrite_event).get("rewritten_query") if rewrite_event else None
    state_rewritten_query = adk_parser.state_after(agent_output, "rewritten_query")

    return Stage1Trace(
        question=test_case.get("input", {}).get("question", ""),
        rewrite_ran=rewrite_event is not None,
        rewritten_query=rewritten_query,
        carried_into_state=bool(rewritten_query) and state_rewritten_query == rewritten_query,
        answer=adk_parser.extract_answer(agent_output),
        context=adk_parser.extract_context(agent_output),
        events=adk_parser.extract_events(agent_output),
        session_id=adk_parser.extract_session_id(agent_output),
        latency_ms=adk_parser.extract_latency_ms(agent_output),
    )
