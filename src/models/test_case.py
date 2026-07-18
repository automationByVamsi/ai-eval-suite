"""
TestCase is the normalised shape of one row of test input, no matter which
agent or stage it targets. See testdata/knowledge_agent/sanity/*.json for
real examples on disk.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from src.models.schemas import MetricMode


class MetricConfig(BaseModel):
    """One entry of a test case's (or a stage's) `metrics:` list."""

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
    metric_mode: Optional[MetricMode] = None

    @classmethod
    def from_json_file(cls, path: str) -> "TestCase":
        import json

        with open(path) as f:
            return cls.model_validate(json.load(f))
