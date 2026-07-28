"""Fact Find Workflow — sanity pack for VERDICT (live responses)."""

from __future__ import annotations

from typing import Any

from src.models.agent_response import AgentResponse
from src.runners.evaluate import evaluate
from src.verdict import obs
from src.verdict.adapters.common import answer_and_keyword_checks
from src.verdict.models import CheckObservation
from src.verdict.registry import AgentPack, register
from tests.fact_find_workflow.ff_eval import prepare_for_judges, suite_for_case

PACK = "sanity"


def _eval_sanity(
    agent: str,
    case: dict[str, Any],
    response: AgentResponse,
    run_judges: bool,
) -> list[CheckObservation]:
    checks = obs.from_deterministic(answer_and_keyword_checks(case, response))
    if run_judges:
        enriched = prepare_for_judges(case, response)
        suite = suite_for_case(case)
        judges = evaluate(agent, suite, case, enriched, publish=False)
        checks.extend(obs.from_judges(judges.judges))
    return checks


register(
    AgentPack(
        agent="fact_find_workflow",
        default_suite="sanity",
        packs={PACK: _eval_sanity},
        sim_fail={PACK: frozenset({"answer_non_empty"})},
    )
)
