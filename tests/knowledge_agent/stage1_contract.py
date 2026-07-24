"""
Stage 1 contract — Query Rewrite & Search Execution (full strategy matrix).

Layer 1: deterministic asserts (execution + state).
Layer 2: judge metric names only — scoring lives in YAML + criteria.

Does NOT call CORTEX. Tests run judges via KnowledgeAgentTest.
"""

from src.models.evaluation_result import DeterministicCheckResult
from src.parsers.knowledge_agent.stage1 import Stage1Parsed

STAGE = "stage1_query_rewrite"

# ---------------------------------------------------------------------------
# Layer 1 — Deterministic Validation Matrix (strategy doc)
# ---------------------------------------------------------------------------

DETERMINISTIC_CHECKS = [
    "input_query_present",
    "rewrite_executed",
    "rewrite_output_valid",
    "state_propagation_intact",
    "search_executed",
    "result_count_positive",
    "downstream_state_available",
]


def assert_input_query_present(parsed: Stage1Parsed) -> None:
    """#1 stateDelta.query exists and is non-empty."""
    assert parsed.state_query and parsed.state_query.strip(), (
        "stateDelta.query is missing or empty"
    )


def assert_rewrite_executed(parsed: Stage1Parsed) -> None:
    """#2 query_rewrite_agent completed successfully in ADK trace."""
    assert parsed.rewrite_ran, "No query_rewrite_agent event found in the trace"
    assert parsed.rewrite_finished_ok, "query_rewrite_agent did not finish successfully"


def assert_rewrite_output_valid(parsed: Stage1Parsed) -> None:
    """#3 rewritten_query present, non-empty, schema-compliant (non-empty string)."""
    assert isinstance(parsed.rewritten_query, str) and parsed.rewritten_query.strip(), (
        "rewritten_query is missing, empty, or not a string"
    )


def assert_state_propagation_intact(parsed: Stage1Parsed) -> None:
    """#4 rewrite output matches downstream state.rewritten_query."""
    assert parsed.carried_into_state, (
        "state.rewritten_query does not match the query_rewrite_agent event output"
    )


def assert_search_executed(parsed: Stage1Parsed) -> None:
    """#5 search_node ran successfully and produced deduplicated_page_ids (positive path)."""
    assert parsed.search_ran, "No search_node event found in the trace"
    assert parsed.search_succeeded, "Search did not report 'Search retrieved successfully'"
    assert parsed.deduplicated_page_ids_count is not None, (
        "deduplicated_page_ids missing from search success message"
    )
    assert parsed.deduplicated_page_ids_count > 0, (
        f"deduplicated_page_ids={parsed.deduplicated_page_ids_count} (expected > 0 on positive path)"
    )


def assert_result_count_positive(parsed: Stage1Parsed) -> None:
    """#6 usable candidates: result_count > 0 (positive path)."""
    assert parsed.result_count is not None, "result_count missing from search success message"
    assert parsed.result_count > 0, (
        f"result_count={parsed.result_count} (expected > 0 on positive path)"
    )


def assert_downstream_state_available(parsed: Stage1Parsed) -> None:
    """#7 artifact_id and rewritten_query accessible to later stages."""
    assert parsed.artifact_id and str(parsed.artifact_id).strip(), (
        "artifact_id missing for downstream stages"
    )
    assert parsed.state_rewritten_query and parsed.state_rewritten_query.strip(), (
        "rewritten_query not available in state for downstream stages"
    )


def run_deterministic(parsed: Stage1Parsed) -> list[DeterministicCheckResult]:
    runners = {
        "input_query_present": assert_input_query_present,
        "rewrite_executed": assert_rewrite_executed,
        "rewrite_output_valid": assert_rewrite_output_valid,
        "state_propagation_intact": assert_state_propagation_intact,
        "search_executed": assert_search_executed,
        "result_count_positive": assert_result_count_positive,
        "downstream_state_available": assert_downstream_state_available,
    }
    results = []
    for name in DETERMINISTIC_CHECKS:
        try:
            runners[name](parsed)
            results.append(DeterministicCheckResult(name=name, passed=True))
        except AssertionError as exc:
            results.append(DeterministicCheckResult(name=name, passed=False, reason=str(exc)))
    return results


# Layer 2 — LLM-as-a-Judge names (must match suite judges: + catalog entries)
# Suite: configs/evaluations/knowledge_agent/stage1_query_rewrite.yaml
# Catalog: configs/metrics/knowledge_agent/catalog.yaml
JUDGE_METRICS = [
    "intent_preservation",
    "semantic_preservation",
    "domain_appropriateness",
    "query_optimization",
]
