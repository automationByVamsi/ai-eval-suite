"""
Register how VERDICT scores each agent.

Add a new agent: write a small adapter, then register() it here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.models.agent_response import AgentResponse
from src.verdict.models import CheckObservation

# (agent, case, live_response, run_judges) -> check observations
EvalFn = Callable[[str, dict[str, Any], AgentResponse, bool], list[CheckObservation]]


@dataclass(frozen=True)
class AgentPack:
    """Describe the packs and helpers available for one agent."""
    agent: str
    default_suite: str = "sanity"
    packs: dict[str, EvalFn] = field(default_factory=dict)
    # Optional: check names to fail under --simulate-regression (demo)
    sim_fail: dict[str, frozenset[str]] = field(default_factory=dict)


_REGISTRY: dict[str, AgentPack] = {}


def register(pack: AgentPack) -> AgentPack:
    """Register an agent pack and return it for inline use."""
    _REGISTRY[pack.agent] = pack
    return pack


def get_pack(agent: str) -> AgentPack:
    """Return the registered pack for an agent name."""
    if agent not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown agent {agent!r} for VERDICT. Registered: {known}")
    return _REGISTRY[agent]


def list_agents() -> list[str]:
    """List registered agent names in sorted order."""
    return sorted(_REGISTRY)


def load_builtin_packs() -> None:
    """Import adapters so they self-register (idempotent)."""
    from src.verdict.adapters import fact_find_workflow as _ff  # noqa: F401
    from src.verdict.adapters import knowledge_agent as _ka  # noqa: F401
