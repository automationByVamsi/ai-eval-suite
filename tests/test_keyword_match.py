"""KeywordMatchMetric is pure Python - no CORTEX/network involved, safe to unit test directly."""

from src.metrics.keyword_match import KeywordMatchMetric
from src.models.agent_response import AgentResponse
from src.models.test_case import TestCase


def _test_case(keywords):
    return TestCase(
        test_case_id="TC_TEST",
        agent_name="knowledge_agent_replay",
        input={"question": "does not matter"},
        expected={"keywords": keywords},
    )


def test_all_keywords_present_passes():
    metric = KeywordMatchMetric(name="keyword_match", threshold=1.0)
    response = AgentResponse(answer="Reset your password using the self-service link.")

    result = metric.evaluate(_test_case(["password", "reset"]), response)

    assert result.passed
    assert result.score == 1.0


def test_missing_keyword_fails():
    metric = KeywordMatchMetric(name="keyword_match", threshold=1.0)
    response = AgentResponse(answer="Contact IT support for help.")

    result = metric.evaluate(_test_case(["password", "reset"]), response)

    assert not result.passed
    assert "password" in result.reason.lower()
