"""Fact Find Workflow fixtures — case loading / validation lives here.

METRICS_SUITE selects configs/evaluations/fact_find_workflow/<suite>.yaml
explicitly (e.g. "sanity" or "e2e") — not derived from case.expected.path.
"""

from __future__ import annotations

import os

import pytest

from tests.support.sanity import load_sanity_cases

AGENT = "fact_find_workflow"
METRICS_SUITE = os.environ.get("METRICS_SUITE", "sanity")

CASES = load_sanity_cases(AGENT, required_input_keys=["complaint_ref"])
CASE_IDS = [c["test_case_id"] for c in CASES]


@pytest.fixture(params=CASES, ids=CASE_IDS)
def case(request: pytest.FixtureRequest) -> dict:
    return request.param
