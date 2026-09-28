"""Load comparison experiment YAML into ComparisonSpec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.comparison.models import (
    CandidateSpec,
    ComparisonDimension,
    ComparisonSpec,
    MetricComparisonConfig,
    MetricDirection,
    MetricRole,
    StatisticsConfig,
)
from src.core.config import get_agent_config, load_metric_catalog, load_yaml
from src.core.exceptions import ConfigError


def load_comparison_spec(
    path: str | Path,
    *,
    agents_path: str | Path = "configs/agents.yaml",
) -> ComparisonSpec:
    """Parse configs/comparisons/*.yaml into a validated ComparisonSpec."""
    data = load_yaml(path)
    raw = data.get("comparison")
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must define a top-level 'comparison:' mapping")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise ConfigError(f"{path}: comparison.name is required")

    candidate_a = _parse_candidate(raw.get("candidate_a"), label="candidate_a")
    candidate_b = _parse_candidate(raw.get("candidate_b"), label="candidate_b")

    dataset = raw.get("dataset") or {}
    if not isinstance(dataset, dict):
        raise ConfigError(f"{path}: comparison.dataset must be a mapping")

    dataset_agent = str(dataset.get("agent") or dataset.get("agent_testdata") or candidate_a.agent)
    dataset_suite = str(dataset.get("suite") or dataset.get("path") or "sanity")
    # Allow dataset.path like testdata/knowledge_agent/sanity
    if dataset.get("path") and not dataset.get("suite"):
        parts = Path(str(dataset["path"])).parts
        if "testdata" in parts:
            i = parts.index("testdata")
            rest = parts[i + 1 :]
            if len(rest) >= 2:
                dataset_agent = rest[0]
                dataset_suite = rest[1]
            elif len(rest) == 1:
                dataset_suite = rest[0]

    evaluation_suite = str(raw.get("evaluation_suite") or dataset_suite)
    repetitions = int(raw.get("repetitions") if raw.get("repetitions") is not None else 6)
    if repetitions < 1:
        raise ConfigError(f"{path}: repetitions must be >= 1")

    stats_raw = raw.get("statistics") or {}
    if not isinstance(stats_raw, dict):
        raise ConfigError(f"{path}: statistics must be a mapping")
    statistics = StatisticsConfig(
        bootstrap_samples=int(stats_raw.get("bootstrap_samples") or 10_000),
        confidence_level=float(stats_raw.get("confidence_level") or 0.95),
        alpha=float(stats_raw.get("alpha") or 0.05),
        seed=int(stats_raw.get("seed") or 42),
        tie_epsilon=float(stats_raw.get("tie_epsilon") or 0.01),
        inflation=float(stats_raw.get("inflation") if stats_raw.get("inflation") is not None else 0.10),
        similarity_consistency_tolerance=float(
            stats_raw.get("similarity_consistency_tolerance")
            if stats_raw.get("similarity_consistency_tolerance") is not None
            else 0.05
        ),
        degraded_share_limit=(
            float(stats_raw["degraded_share_limit"])
            if stats_raw.get("degraded_share_limit") is not None
            else None
        ),
    )

    dimension = _parse_dimension(raw.get("dimension"))
    mode = str(raw.get("mode") or "offline").strip().lower()
    if mode not in {"offline", "live"}:
        raise ConfigError(f"{path}: mode must be 'offline' or 'live', got {mode!r}")

    fixtures = raw.get("fixtures") or {}
    fixtures_path = None
    if isinstance(fixtures, dict) and fixtures.get("path"):
        fixtures_path = str(fixtures["path"])
    elif isinstance(raw.get("fixtures_path"), str):
        fixtures_path = raw["fixtures_path"]

    if mode == "offline" and not fixtures_path:
        raise ConfigError(f"{path}: offline mode requires fixtures.path")

    metric_configs = _load_metric_comparison_configs(
        raw,
        agent_a=candidate_a.agent,
        agents_path=agents_path,
    )

    warnings = _dimension_warnings(
        dimension=dimension,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        agents_path=agents_path,
        mode=mode,
    )

    return ComparisonSpec(
        name=name,
        description=str(raw.get("description") or ""),
        dimension=dimension,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        dataset_agent=dataset_agent,
        dataset_suite=dataset_suite,
        evaluation_suite=evaluation_suite,
        repetitions=repetitions,
        statistics=statistics,
        metric_configs=metric_configs,
        mode=mode,
        fixtures_path=fixtures_path,
        output_dir=str(raw.get("output_dir") or "outputs/comparison"),
        warnings=warnings,
        latency_p95_budget_ms=(
            float(raw["latency_p95_budget_ms"])
            if raw.get("latency_p95_budget_ms") is not None
            else None
        ),
        cost_budget_per_task=(
            float(raw["cost_budget_per_task"])
            if raw.get("cost_budget_per_task") is not None
            else None
        ),
        require_similarity=bool(raw.get("require_similarity", True)),
        require_stability=bool(raw.get("require_stability", True)),
        require_judge_reliability=bool(raw.get("require_judge_reliability", True)),
        divergences_reviewed=bool(raw.get("divergences_reviewed", False)),
    )


def _parse_candidate(raw: Any, *, label: str) -> CandidateSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")
    name = str(raw.get("name") or label)
    agent = str(raw.get("agent") or "").strip()
    if not agent:
        raise ConfigError(f"{label}.agent is required (agents.yaml key)")
    metadata = dict(raw.get("metadata") or {})
    # Preserve overrides as metadata only — ADK cannot apply model/prompt switches.
    overrides = raw.get("overrides")
    if isinstance(overrides, dict) and overrides:
        metadata = {**metadata, "overrides": overrides, "overrides_applied": False}
    return CandidateSpec(name=name, agent=agent, metadata=metadata)


def _parse_dimension(value: Any) -> ComparisonDimension:
    if value is None:
        return ComparisonDimension.OTHER
    text = str(value).strip().lower()
    try:
        return ComparisonDimension(text)
    except ValueError:
        return ComparisonDimension.OTHER


def _parse_role(value: Any) -> MetricRole:
    try:
        return MetricRole(str(value).strip().lower())
    except ValueError:
        return MetricRole.DIAGNOSTIC


def _parse_direction(value: Any) -> MetricDirection:
    text = str(value or "larger_is_better").strip().lower()
    if text in {"smaller_is_better", "lower_is_better", "minimize"}:
        return MetricDirection.SMALLER_IS_BETTER
    return MetricDirection.LARGER_IS_BETTER


def _metric_cfg_from_mapping(raw: dict[str, Any]) -> MetricComparisonConfig:
    return MetricComparisonConfig(
        role=_parse_role(raw.get("role")),
        direction=_parse_direction(raw.get("direction")),
        non_inferiority_margin=(
            float(raw["non_inferiority_margin"])
            if raw.get("non_inferiority_margin") is not None
            else None
        ),
        critical=bool(raw.get("critical") or False),
        allowed_events=int(raw.get("allowed_events") or 0),
        tie_epsilon=(
            float(raw["tie_epsilon"]) if raw.get("tie_epsilon") is not None else None
        ),
        binary=bool(raw.get("binary") or False),
    )


def _load_metric_comparison_configs(
    raw: dict[str, Any],
    *,
    agent_a: str,
    agents_path: str | Path,
) -> dict[str, MetricComparisonConfig]:
    """Merge catalog optional comparison: blocks with experiment-level metrics:."""
    configs: dict[str, MetricComparisonConfig] = {}

    # Catalog (optional — missing catalog is fine for offline synthetic demos)
    try:
        from src.core.config import agent_metrics_profile

        profile = agent_metrics_profile(agent_a, path=agents_path)
        catalog = load_metric_catalog(profile)
        for name, entry in catalog.items():
            cmp_block = entry.get("comparison")
            if isinstance(cmp_block, dict):
                configs[name] = _metric_cfg_from_mapping(cmp_block)
    except Exception:  # noqa: BLE001 — offline demos may lack agents/catalog
        pass

    # Experiment-level overrides win
    metrics_block = raw.get("metrics") or {}
    if isinstance(metrics_block, dict):
        for name, entry in metrics_block.items():
            if not isinstance(entry, dict):
                continue
            inner = entry.get("comparison") if isinstance(entry.get("comparison"), dict) else entry
            configs[str(name)] = _metric_cfg_from_mapping(inner)

    return configs


def _dimension_warnings(
    *,
    dimension: ComparisonDimension,
    candidate_a: CandidateSpec,
    candidate_b: CandidateSpec,
    agents_path: str | Path,
    mode: str,
) -> list[str]:
    warnings: list[str] = []
    ov_a = (candidate_a.metadata.get("overrides") or {}) if candidate_a.metadata else {}
    ov_b = (candidate_b.metadata.get("overrides") or {}) if candidate_b.metadata else {}
    if ov_a or ov_b:
        warnings.append(
            "candidate overrides are recorded as metadata only; "
            "ADK invocation does not apply model/prompt/tool overrides at runtime."
        )
        changed = set(ov_a) | set(ov_b)
        if len(changed) > 1:
            warnings.append(
                f"Multiple override keys differ ({sorted(changed)}); "
                f"declared dimension is '{dimension.value}' — verify only one intended dimension changed."
            )

    if mode == "live" and candidate_a.agent == candidate_b.agent:
        warnings.append(
            "Live mode uses the same agents.yaml key for A and B; "
            "both arms hit the same ADK endpoint unless deployments differ externally."
        )

    if mode == "live":
        try:
            cfg_a = get_agent_config(candidate_a.agent, path=agents_path)
            cfg_b = get_agent_config(candidate_b.agent, path=agents_path)
            same_endpoint = (
                str(cfg_a.get("base_url")) == str(cfg_b.get("base_url"))
                and str(cfg_a.get("app_name")) == str(cfg_b.get("app_name"))
            )
            if same_endpoint and dimension == ComparisonDimension.MODEL:
                warnings.append(
                    "dimension=model but Candidate A and B resolve to the same base_url+app_name."
                )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Could not validate agent endpoints: {exc}")

    return warnings
