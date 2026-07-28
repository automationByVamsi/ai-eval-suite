"""Build DeepEval EvolutionConfig from evolution.yaml."""

from __future__ import annotations

from pathlib import Path

from deepeval.synthesizer.config import EvolutionConfig
from deepeval.synthesizer.types import Evolution

from src.core.config import load_yaml

_EVOLUTION_BY_NAME = {e.name: e for e in Evolution}


def build_evolution_config(path: Path | None) -> EvolutionConfig | None:
    """Load evolution weights from YAML when a config file is present."""
    if path is None or not path.is_file():
        return None
    evo = load_yaml(path)
    raw_map = evo.get("evolutions") or {}
    evolutions: dict[Evolution, float] = {}
    for name, weight in raw_map.items():
        key = str(name).upper().replace("-", "_").replace(" ", "_")
        if key not in _EVOLUTION_BY_NAME:
            raise ValueError(
                f"Unknown evolution {name!r}. Known: {sorted(_EVOLUTION_BY_NAME)}"
            )
        evolutions[_EVOLUTION_BY_NAME[key]] = float(weight)
    if evolutions:
        return EvolutionConfig(
            num_evolutions=int(evo.get("num_evolutions", 1)),
            evolutions=evolutions,
        )
    return EvolutionConfig(num_evolutions=int(evo.get("num_evolutions", 1)))
