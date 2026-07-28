"""Knowledge Agent fixtures — case loading / validation lives here.

METRICS_SUITE selects configs/evaluations/knowledge_agent/<suite>.yaml
explicitly (e.g. "sanity" or "e2e").
"""

from __future__ import annotations

import pytest

from tests.support.sanity import load_sanity_cases

AGENT = "knowledge_agent"
METRICS_SUITE = "sanity"

CASES = load_sanity_cases(AGENT, required_input_keys=["question"])
CASE_IDS = [c["test_case_id"] for c in CASES]


@pytest.fixture(params=CASES, ids=CASE_IDS)
def case(request: pytest.FixtureRequest) -> dict:
    return request.param
