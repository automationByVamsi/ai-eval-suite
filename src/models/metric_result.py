from pydantic import BaseModel


class MetricResult(BaseModel):
    """Result for one metric or judge after evaluation."""
    name: str
    score: float
    threshold: float
    passed: bool
    reason: str = ""
