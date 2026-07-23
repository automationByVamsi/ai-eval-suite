"""Save / load trusted-release baselines for regression diffs."""

from __future__ import annotations

import json
from pathlib import Path

from src.verdict.models import MetricAggregate


def baseline_path(root: str | Path, profile: str, name: str = "latest") -> Path:
    return Path(root) / profile / f"{name}.json"


def save_baseline(
    aggregates: list[MetricAggregate],
    *,
    root: str | Path = "outputs/verdict/baselines",
    profile: str,
    name: str = "latest",
    meta: dict | None = None,
) -> Path:
    path = baseline_path(root, profile, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": profile,
        "meta": meta or {},
        "metrics": [a.model_dump() for a in aggregates],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_baseline(
    *,
    root: str | Path = "outputs/verdict/baselines",
    profile: str,
    name: str = "latest",
) -> list[MetricAggregate]:
    path = baseline_path(root, profile, name)
    if not path.is_file():
        raise FileNotFoundError(f"No baseline at {path}")
    data = json.loads(path.read_text())
    return [MetricAggregate.model_validate(m) for m in data.get("metrics", [])]
