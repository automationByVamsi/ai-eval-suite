"""
Comparison orchestration.

- offline: load synthetic / precomputed RunObservation fixtures
- live: invoke each candidate agent on the same cases × reps (namespaced traces)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.comparison.engine import analyze_comparison
from src.comparison.models import ComparisonResult, ComparisonSpec, RunObservation
from src.comparison.report import print_comparison_report, write_comparison_json


def run_comparison(
    spec: ComparisonSpec,
    *,
    run_stability: bool = False,
    agents_path: str = "configs/agents.yaml",
    cortex_config: str = "configs/cortex.yaml",
) -> ComparisonResult:
    """Execute (or load) observations and produce a ComparisonResult."""
    if spec.mode == "offline":
        observations = load_fixture_observations(spec.fixtures_path)
    else:
        observations = collect_live_observations(
            spec,
            agents_path=agents_path,
            cortex_config=cortex_config,
        )

    result = analyze_comparison(
        spec,
        observations,
        run_stability=run_stability,
        divergences_reviewed=bool(spec.divergences_reviewed),
    )

    out_dir = Path(spec.output_dir) / spec.name
    out_dir.mkdir(parents=True, exist_ok=True)
    write_comparison_json(result, out_dir / "comparison_result.json")
    print_comparison_report(result)
    return result


def load_fixture_observations(path: str | Path | None) -> list[RunObservation]:
    """Load offline fixture JSON into RunObservation list."""
    if not path:
        raise FileNotFoundError("fixtures_path is required for offline comparison")
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Comparison fixtures not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "observations" in data:
        rows = data["observations"]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError(f"Fixture {p} must be a list or {{observations: [...]}}")

    out: list[RunObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Invalid observation row in {p}: {row!r}")
        out.append(RunObservation.model_validate(row))
    return out


def collect_live_observations(
    spec: ComparisonSpec,
    *,
    agents_path: str = "configs/agents.yaml",
    cortex_config: str = "configs/cortex.yaml",
) -> list[RunObservation]:
    """
    Live ADK path: same dataset for A and B; traces namespaced by candidate.

    Uses case_runner + evaluate so scoring matches existing suites.
    """
    # Local imports keep offline/unit-test path free of heavy deps at import time
    from src.runners.case_runner import load_cases, run_case
    from src.runners.evaluate import evaluate

    cases = load_cases(spec.dataset_agent, spec.dataset_suite)
    observations: list[RunObservation] = []

    arms = [
        ("a", spec.candidate_a),
        ("b", spec.candidate_b),
    ]
    prev_disable = os.environ.get("DASHBOARD_DISABLE")
    os.environ["DASHBOARD_DISABLE"] = "1"
    try:
        for arm_key, candidate in arms:
            for case in cases:
                case_id = str(case["test_case_id"])
                for rep in range(spec.repetitions):
                    trace_root = (
                        Path(spec.output_dir)
                        / spec.name
                        / "traces"
                        / arm_key
                        / f"rep_{rep}"
                    )
                    print(
                        f"[comparison] live {arm_key}/{candidate.agent} "
                        f"case={case_id} rep={rep + 1}/{spec.repetitions}"
                    )
                    live = run_case(
                        candidate.agent,
                        case,
                        spec.dataset_suite,
                        output_dir=trace_root,
                        agents_path=agents_path,
                        mode="live",
                    )
                    eval_result = evaluate(
                        candidate.agent,
                        spec.evaluation_suite,
                        case,
                        live.response,
                        agents_path=agents_path,
                        cortex_config=cortex_config,
                        publish=False,
                    )
                    latency = live.response.latency_ms
                    answer = live.response.answer or ""
                    for judge in eval_result.judges:
                        observations.append(
                            RunObservation(
                                candidate=arm_key,
                                test_case_id=case_id,
                                metric_name=judge.name,
                                rep=rep,
                                score=judge.score,
                                passed=judge.passed,
                                latency_ms=latency,
                                reason=judge.reason or "",
                                critical_event=False,
                                answer=answer,
                            )
                        )
                    if latency is not None:
                        observations.append(
                            RunObservation(
                                candidate=arm_key,
                                test_case_id=case_id,
                                metric_name="latency_ms",
                                rep=rep,
                                score=float(latency),
                                passed=True,
                                latency_ms=latency,
                                answer=answer,
                            )
                        )
    finally:
        if prev_disable is None:
            os.environ.pop("DASHBOARD_DISABLE", None)
        else:
            os.environ["DASHBOARD_DISABLE"] = prev_disable

    return observations


def observations_from_score_matrix(
    matrix: dict[str, Any],
) -> list[RunObservation]:
    """
    Convenience builder for tests/demos.

    Expected shape:
      {
        "metrics": {
          "correctness": {
            "a": {"TC001": [0.8, 0.82], ...},
            "b": {"TC001": [0.85, 0.86], ...}
          }
        },
        "critical_events": {  # optional
          "privacy_leakage": {"a": {"TC001": [false]}, "b": {"TC001": [true]}}
        }
      }
    """
    out: list[RunObservation] = []
    metrics = matrix.get("metrics") or {}
    for metric_name, arms in metrics.items():
        for arm in ("a", "b"):
            cases = (arms or {}).get(arm) or {}
            for case_id, runs in cases.items():
                for rep, score in enumerate(runs):
                    out.append(
                        RunObservation(
                            candidate=arm,
                            test_case_id=str(case_id),
                            metric_name=str(metric_name),
                            rep=rep,
                            score=float(score) if score is not None else None,
                        )
                    )
    critical = matrix.get("critical_events") or {}
    for metric_name, arms in critical.items():
        for arm in ("a", "b"):
            cases = (arms or {}).get(arm) or {}
            for case_id, runs in cases.items():
                for rep, flag in enumerate(runs):
                    out.append(
                        RunObservation(
                            candidate=arm,
                            test_case_id=str(case_id),
                            metric_name=str(metric_name),
                            rep=rep,
                            score=1.0 if flag else 0.0,
                            passed=not bool(flag),
                            critical_event=bool(flag),
                        )
                    )
    return out
