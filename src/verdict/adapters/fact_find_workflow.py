"""Fact Find Workflow — sanity pack for VERDICT (live responses)."""

from __future__ import annotations

from typing import Any

from src.eval import prepare_sample
from src.models.agent_response import AgentResponse
from src.parsers.fact_find_workflow import prepare_response
from src.runners.evaluate import evaluate
from src.verdict import obs
from src.verdict.models import CheckObservation
from src.verdict.registry import AgentPack, register
from tests.fact_find_workflow.ff_eval import run_deterministic

PACK = "sanity"


def _eval_sanity(
    agent: str,
    case: dict[str, Any],
    response: AgentResponse,
    run_judges: bool,
) -> list[CheckObservation]:
    """Run deterministic checks and optional judges for one Fact Find case."""
    complaint_ref = (case.get("input") or {}).get("complaint_ref") or ""
    raw = response.raw_output if isinstance(response.raw_output, dict) else {}
    det, _fields = run_deterministic(case, raw, complaint_ref)
    checks = obs.from_deterministic(det)
    if run_judges:
        enriched = prepare_sample(case, prepare_response(case, response))
        judges = evaluate(agent, PACK, case, enriched, publish=False)
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
