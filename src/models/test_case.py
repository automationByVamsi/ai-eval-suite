"""
TestCase is the normalised shape of one row of test input for any agent.
See testdata/<agent>/<tag>/*.json for examples on disk.

Metrics selection (Knowledge Agent):
  - `suite`: name under configs/evaluations/<profile>/ (e.g. sanity, e2e)
  - `metrics`: optional name list / overrides (rare); empty → suite or profile default
  Same case JSON can be run under any suite — suite is an evaluation lens on the response.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class MetricConfig(BaseModel):
    """One entry of a test case's `metrics:` list."""

    name: str
    threshold: Optional[float] = None
    type: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)


class TestCase(BaseModel):
    """Normalized test case loaded from JSON input data."""
    __test__ = False  # tell pytest this isn't a test class, despite the name

    test_case_id: str
    description: str = ""
    agent_name: str = ""
    input: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    suite: Optional[str] = None
    metrics: list[MetricConfig] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str) -> "TestCase":
        """Load and validate one test case JSON file."""
        import json

        with open(path) as f:
            return cls.model_validate(json.load(f))
