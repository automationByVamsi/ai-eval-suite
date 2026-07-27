"""Build DeepEval FiltrationConfig from filtration.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.synthesizer.config import FiltrationConfig

from src.core.config import load_yaml


def load_filtration_settings(path: Path | None) -> dict[str, Any] | None:
    """Read filtration.yaml without constructing DeepEval (no OpenAI default)."""
    if path is None or not path.is_file():
        return None
    data = load_yaml(path)
    return {
        "synthetic_input_quality_threshold": float(
            data.get("synthetic_input_quality_threshold", 0.5)
        ),
        "max_quality_retries": int(data.get("max_quality_retries", 3)),
    }


def build_filtration_config(
    path: Path | None,
    *,
    critic_model: DeepEvalBaseLLM | None = None,
) -> FiltrationConfig | None:
    """
    Quality gate for synthetic questions.

    critic_model is required (use CORTEX DeepEval adapter). Without it we
    return None so DeepEval does not fall back to OpenAI.
    """
    settings = load_filtration_settings(path)
    if settings is None or critic_model is None:
        return None
    return FiltrationConfig(
        synthetic_input_quality_threshold=settings["synthetic_input_quality_threshold"],
        max_quality_retries=settings["max_quality_retries"],
        critic_model=critic_model,
    )
