"""
evalkit — evaluate AI agents: call the agent, save the trace, run checks + LLM judges,
report pass/fail, and compare builds against a baseline.

Read in this order: runner.py (the flow) -> judges.py -> verdict.py -> adk.py.
Parsers import `check` and the ADK trace helpers from here.
"""

from evalkit import adk
from evalkit.results import Result, check

__all__ = ["adk", "check", "Result"]
