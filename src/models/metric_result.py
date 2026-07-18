from pydantic import BaseModel


class MetricResult(BaseModel):
    name: str
    score: float
    threshold: float
    passed: bool
    reason: str = ""
