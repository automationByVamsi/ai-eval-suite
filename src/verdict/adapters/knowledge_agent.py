"""Knowledge Agent — sanity pack for VERDICT (live responses)."""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse
from src.runners.evaluate import evaluate
from src.verdict import obs
from src.verdict.adapters.common import answer_and_keyword_checks
from src.verdict.models import CheckObservation
from src.verdict.registry import AgentPack, register

PACK = "sanity"


def _eval_sanity(
    agent: str,
    case: dict[str, Any],
    response: AgentResponse,
    run_judges: bool,
) -> list[CheckObservation]:
    meta = dict(response.metadata or {})
    meta.setdefault("question", (case.get("input") or {}).get("question") or "")
    response = response.model_copy(update={"metadata": meta})

    checks = obs.from_deterministic(answer_and_keyword_checks(case, response))
    if run_judges:
        judges = evaluate(agent, PACK, case, response, publish=False)
        checks.extend(obs.from_judges(judges.judges))
    return checks


register(
    AgentPack(
        agent="knowledge_agent",
        default_suite="sanity",
        packs={PACK: _eval_sanity},
        sim_fail={PACK: frozenset({"answer_non_empty"})},
    )
)
