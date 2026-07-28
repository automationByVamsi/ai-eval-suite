"""
Config-only metrics: a YAML block (type: geval) + a Markdown rubric file is
all it takes to add a brand-new LLM-judge metric - no Python class, no core
change. See configs/metrics/<agent>/catalog.yaml +
configs/evaluations/<agent>/<suite>.yaml and a rubric under configs/criteria/.
"""

from pathlib import Path

from deepeval.metrics import GEval
from deepeval.test_case import SingleTurnParams

from src.core.exceptions import ConfigError
from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import DeepEvalMetric

_PARAM_MAP = {
    "input": SingleTurnParams.INPUT,
    "actual_output": SingleTurnParams.ACTUAL_OUTPUT,
    "expected_output": SingleTurnParams.EXPECTED_OUTPUT,
    "context": SingleTurnParams.CONTEXT,
    "retrieval_context": SingleTurnParams.RETRIEVAL_CONTEXT,
}


@METRIC_REGISTRY.register("geval")
class CustomGEval(DeepEvalMetric):
    def __init__(self, *args, rubric: str, **kwargs):
        super().__init__(*args, **kwargs)
        rubric_path = Path(rubric)
        if not rubric_path.exists():
            raise ConfigError(f"GEval rubric file not found: {rubric_path}")
        self.criteria = rubric_path.read_text().strip()

    def build_deepeval_metric(self):
        unknown = [p for p in self.evaluation_params if p not in _PARAM_MAP]
        if unknown:
            raise ConfigError(
                f"Unknown GEval evaluation_params {unknown}. Allowed: {sorted(_PARAM_MAP)}"
            )
        params = [_PARAM_MAP[p] for p in self.evaluation_params]
        return GEval(
            name=self.name,
            criteria=self.criteria,
            evaluation_params=params,
            model=self.cortex_llm,
            threshold=self.threshold,
        )
