"""Baseline and verdict."""

import pytest

from src.core import results
from src.core.results import load_run
from src.runners.suite_runner import run_suite
from src.verdict.baseline import save_baseline
from src.verdict.compare import compare

# A Knowledge Agent sanity case whose committed trace passes every check.
PASSING = ["TC_002"]


def test_verdict_passes_against_itself_and_catches_a_regression(outputs):
    stable = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.0", case_ids=PASSING)
    save_baseline(stable)

    passed, rows, _ = compare(stable)
    assert passed and all(r["status"] == "ok" for r in rows)

    broken = load_run(stable.run_id)
    broken.cases[0].results[0].status = results.FAIL      # answer_non_empty now fails
    passed, rows, _ = compare(broken)
    assert not passed
    assert [r["result"] for r in rows if r["status"] == "regression"] == ["TC_002 :: check:answer_non_empty"]


def test_score_drop_is_a_regression_even_above_threshold(outputs):
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=PASSING)
    judge = results.Result("faithfulness", "judge", results.PASS, score=0.95, threshold=0.7, engine="pegasus")
    run.cases[0].results.append(judge)
    save_baseline(run)
    judge.score = 0.80                                     # still passes, but dropped 0.15
    passed, rows, _ = compare(run)
    assert not passed
    assert any(r["status"] == "regression" and "faithfulness" in r["result"] for r in rows)


def test_no_baseline_from_a_broken_run(outputs):
    (outputs / "outputs/traces/knowledge_agent/sanity/TC_012.json").unlink()
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False)   # TC_012 errors: no trace
    with pytest.raises(ValueError, match="errors"):
        save_baseline(run)
