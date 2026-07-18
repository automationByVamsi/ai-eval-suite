"""
Importing this package registers every built-in agent adapter with
AGENT_REGISTRY. AgentFactory imports this package once, on startup, so it
never has to import a concrete adapter class by name.
"""

from src.agents import adk_agent_adapter, replay_agent_adapter  # noqa: F401
