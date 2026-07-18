"""Small shared enums/types used across models, evaluators, and metrics."""

from enum import Enum


class MetricMode(str, Enum):
    """Which judge metrics run for a pipeline stage."""

    STAGE_ONLY = "stage_only"
    GLOBAL_ONLY = "global_only"
    STAGE_PLUS_GLOBAL = "stage_plus_global"
