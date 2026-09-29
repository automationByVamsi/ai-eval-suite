"""
Optional. Delete this file if the standard fields are enough:
    question        = the case input sent to the agent
    answer          = the agent's final answer
    contexts        = trace["context"] if the agent returns one
    expected_answer = case expected.expected_answer

Add a parse() to expose more fields from the trace (judges can point at them in agent.yaml),
and a checks() for deterministic checks specific to this agent.
"""

from evalkit import adk, check  # noqa: F401 — used by the commented examples below


def parse(trace, case):
    return {
        # "rewritten_query": adk.state(trace, "rewritten_query", ""),
        # "tools_called": [c["name"] for c in adk.tool_calls(trace)],
    }


def checks(fields, case):
    return [
        # check("mentions_customer", "customer" in fields["answer"].lower(), "no mention of the customer"),
    ]
