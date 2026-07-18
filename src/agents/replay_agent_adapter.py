"""
Reads a previously-captured trace off disk instead of calling a live agent.
This is what makes "capture once, evaluate many times, offline" possible
(see scripts/capture_traces.py) and it's the adapter used by every sample
test case in this repo, since it needs no live agent or network access.
"""

import json
import time
from pathlib import Path
from typing import Any

from src.agents import adk_parser
from src.agents.base_agent import BaseAgent
from src.core.exceptions import TraceParseError
from src.core.registry import AGENT_REGISTRY
from src.models.agent_response import AgentResponse


@AGENT_REGISTRY.register("replay")
class ReplayAgentAdapter(BaseAgent):
    """config: {trace_dir: outputs/traces/<agent>/<tag>}"""

    def invoke(self, payload: dict[str, Any]) -> AgentResponse:
        test_case_id = payload.get("_test_case_id")
        if not test_case_id:
            raise TraceParseError("ReplayAgentAdapter requires payload['_test_case_id']")

        trace_path = Path(self.config["trace_dir"]) / f"{test_case_id}.json"
        if not trace_path.exists():
            raise TraceParseError(
                f"No captured trace found at {trace_path}. Run scripts/capture_traces.py first."
            )

        start = time.perf_counter()
        with trace_path.open() as f:
            trace = json.load(f)
        raw = trace.get("raw_output", trace)

        return AgentResponse(
            answer=adk_parser.extract_answer(raw),
            raw_output=raw,
            context=adk_parser.extract_context(raw),
            events=adk_parser.extract_events(raw),
            metadata={},
            session_id=adk_parser.extract_session_id(raw),
            latency_ms=adk_parser.extract_latency_ms(raw) or (time.perf_counter() - start) * 1000,
        )
