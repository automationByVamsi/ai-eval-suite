"""
Decides which judge metrics run for a stage, based on configs/evaluations/
<agent>/<stage>.yaml's `mode` (or a per-test-case override):

- stage_only:         only this stage's judge_metrics
- global_only:        only the agent's base_metrics (configs/metrics/<agent>.yaml)
- stage_plus_global:  both (the default)

If a test case declares its own `metrics:` list, those names win - existing
config (type, rubric, sources, ...) is kept and only the threshold is
overridden, so a test case can tighten/loosen a threshold without having to
redeclare the whole metric.
"""

from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.schemas import MetricMode
from src.models.test_case import TestCase
from src.runners.factories import MetricFactory


class StageMetricRunner:
    def __init__(self, metric_factory: MetricFactory, agent_profile: str, stage_config: dict):
        self.metric_factory = metric_factory
        self.agent_profile = agent_profile
        self.stage_config = stage_config

    def run(self, test_case: TestCase, response: AgentResponse) -> list[MetricResult]:
        mode = test_case.metric_mode or MetricMode(self.stage_config.get("mode", MetricMode.STAGE_PLUS_GLOBAL.value))

        stage_metrics = self.stage_config.get("judge_metrics", [])
        global_metrics = self.metric_factory.load_base_metrics(self.agent_profile)

        if mode == MetricMode.STAGE_ONLY:
            available = stage_metrics
        elif mode == MetricMode.GLOBAL_ONLY:
            available = global_metrics
        else:
            available = stage_metrics + global_metrics

        if test_case.metrics:
            by_name = {m["name"]: m for m in available}
            metric_configs = []
            for override in test_case.metrics:
                cfg = dict(by_name.get(override.name, {"name": override.name}))
                if override.threshold is not None:
                    cfg["threshold"] = override.threshold
                metric_configs.append(cfg)
        else:
            metric_configs = available

        return [self.metric_factory.create(cfg).evaluate(test_case, response) for cfg in metric_configs]
