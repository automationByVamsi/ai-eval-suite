"""
Every agent - live HTTP-backed, offline replay, or a future LangGraph/CrewAI
adapter - implements this one method. Agents never depend on CORTEX; only
metrics do (see clients/cortex_deepeval.py and metrics/base_metric.py).
"""

from abc import ABC, abstractmethod
from typing import Any

from src.models.agent_response import AgentResponse


class BaseAgent(ABC):
    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def invoke(self, payload: dict[str, Any]) -> AgentResponse:
        """Run the agent on one input payload and return a normalised AgentResponse."""
        raise NotImplementedError
