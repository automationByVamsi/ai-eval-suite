"""
TestCase is the normalised shape of one row of test input for any agent.
See testdata/<agent>/<tag>/*.json for examples on disk.
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
    __test__ = False  # tell pytest this isn't a test class, despite the name

    test_case_id: str
    description: str = ""
    agent_name: str
    input: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    metrics: list[MetricConfig] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str) -> "TestCase":
        import json

        with open(path) as f:
            return cls.model_validate(json.load(f))
