"""Unit tests for suite mode → per-metric backend resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.config import resolve_suite_metrics
from src.core.metric_mode import (
    backends_for,
    preferred_suite_mode,
    resolve_metric_mode,
)


def test_backends_geval_only() -> None:
    assert backends_for({"type": "geval", "name": "intent_preservation"}) == ["deepeval"]


def test_backends_portable() -> None:
    assert backends_for({"type": "faithfulness", "name": "faithfulness"}) == [
        "pegasus",
        "deepeval",
    ]


def test_backends_explicit_wins() -> None:
    assert backends_for(
        {"type": "relevance", "backends": ["deepeval"], "name": "relevance"}
    ) == ["deepeval"]


def test_resolve_pegasus_preferred_on_portable() -> None:
    cfg = {"type": "relevance", "backends": ["pegasus", "deepeval"], "name": "relevance"}
    assert resolve_metric_mode("pegasus", cfg) == "pegasus"
    assert resolve_metric_mode("pegasus_ragas", cfg) == "pegasus_ragas"


def test_resolve_pegasus_falls_back_for_geval() -> None:
    cfg = {"type": "geval", "backends": ["deepeval"], "name": "intent_preservation"}
    assert resolve_metric_mode("pegasus", cfg) == "deepeval"


def test_judge_override_wins() -> None:
    cfg = {"type": "faithfulness", "backends": ["pegasus", "deepeval"], "name": "faithfulness"}
    assert (
        resolve_metric_mode("pegasus", cfg, judge_override="deepeval") == "deepeval"
    )


def test_metric_mode_env_overrides_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRIC_MODE", "deepeval")
    assert preferred_suite_mode("pegasus") == "deepeval"
    monkeypatch.delenv("METRIC_MODE", raising=False)
    assert preferred_suite_mode("pegasus") == "pegasus"


def test_ka_sanity_mixed_resolution() -> None:
    """sanity prefers pegasus; portable metrics use it (GEval would fall back)."""
    # Clear env so suite mode wins.
    env_mode = os.environ.pop("METRIC_MODE", None)
    try:
        metrics = resolve_suite_metrics("knowledge_agent", "sanity")
        by_name = {m["name"]: m for m in metrics}
        assert by_name["relevance"]["mode"] == "pegasus"
        assert by_name["correctness"]["mode"] == "pegasus"
    finally:
        if env_mode is not None:
            os.environ["METRIC_MODE"] = env_mode


def test_ka_e2e_geval_stays_deepeval() -> None:
    env_mode = os.environ.pop("METRIC_MODE", None)
    try:
        metrics = resolve_suite_metrics("knowledge_agent", "e2e")
        by_name = {m["name"]: m for m in metrics}
        assert by_name["intent_preservation"]["mode"] == "deepeval"
        assert by_name["relevance"]["mode"] == "pegasus"
        assert by_name["keyword_match"]["mode"] == "deepeval"
    finally:
        if env_mode is not None:
            os.environ["METRIC_MODE"] = env_mode


def test_ff_sanity_mixed_backends() -> None:
    env_mode = os.environ.pop("METRIC_MODE", None)
    try:
        metrics = resolve_suite_metrics("fact_find_workflow", "sanity")
        by_name = {m["name"]: m for m in metrics}
        assert by_name["relevance"]["mode"] == "pegasus"
        assert by_name["summarization"]["mode"] == "deepeval"
    finally:
        if env_mode is not None:
            os.environ["METRIC_MODE"] = env_mode


def test_legacy_pegasus_alias() -> None:
    env_mode = os.environ.pop("METRIC_MODE", None)
    try:
        # Temporary suite file would be heavy; call catalog lookup via a tiny
        # in-memory path using resolve against sanity_pegasus names.
        metrics = resolve_suite_metrics("knowledge_agent", "sanity_pegasus")
        names = {m["name"] for m in metrics}
        assert "relevance" in names
        assert "context_precision" in names
        assert all(m["mode"].startswith("pegasus") for m in metrics)
    finally:
        if env_mode is not None:
            os.environ["METRIC_MODE"] = env_mode


def test_per_judge_mode_override_in_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Suite YAML {name, mode} overrides suite-level mode for one judge."""
    metrics_dir = tmp_path / "metrics" / "demo"
    evals_dir = tmp_path / "evaluations" / "demo"
    metrics_dir.mkdir(parents=True)
    evals_dir.mkdir(parents=True)
    (metrics_dir / "catalog.yaml").write_text(
        """
default_suite: sanity
metrics:
  relevance:
    type: relevance
    backends: [pegasus, deepeval]
    threshold: 0.7
  faithfulness:
    type: faithfulness
    backends: [pegasus, deepeval]
    threshold: 0.7
""",
        encoding="utf-8",
    )
    (evals_dir / "sanity.yaml").write_text(
        """
suite: sanity
mode: pegasus
judges:
  - relevance
  - name: faithfulness
    mode: deepeval
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("METRIC_MODE", raising=False)
    resolved = resolve_suite_metrics(
        "demo",
        "sanity",
        metrics_dir=tmp_path / "metrics",
        evals_dir=tmp_path / "evaluations",
    )
    by_name = {m["name"]: m for m in resolved}
    assert by_name["relevance"]["mode"] == "pegasus"
    assert by_name["faithfulness"]["mode"] == "deepeval"
