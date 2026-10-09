"""Baseline and verdict."""

import json

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


# --- rates across a run / several runs (src/reporting/summary.py) -------------------------------

def test_anchor_hit_rate_across_cases_reps_and_runs(outputs, monkeypatch, capsys):
    from src import cli
    from src.reporting.summary import summarise
    from src.runners import test_cases

    real_load = test_cases.load_cases

    def with_expected_anchors(agent, suite):          # TC_002 expects the page it picks, TC_012 another one
        cases = real_load(agent, suite)
        for case in cases:
            case["expected"]["expected_anchor_page_ids"] = ["40345"] if case["test_case_id"] == "TC_002" else ["99999"]
        return cases

    monkeypatch.setattr("src.runners.suite_runner.load_cases", with_expected_anchors)
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, reps=3)
    rows = {r["name"]: r for r in summarise([run])}
    hit = rows["anchor_hit"]
    assert (hit["pass"], hit["fail"], hit["rate"], hit["cases"]) == (3, 3, 0.5, 2)   # 2 cases x 3 reps
    assert hit["unstable"] == {}                                                       # same outcome every rep
    assert rows["expansion_recall"]["rate"] is None                                 # never had expected data
    assert "summary" in json.loads((run.folder / "results.json").read_text())

    run_suite("knowledge_agent", "sanity", offline=True, judges=False)                 # a second run
    assert cli.main(["summary", "knowledge_agent", "sanity", "--last", "2"]) == 0
    out = capsys.readouterr().out
    assert "Rates over 2 run(s), 8 case runs" in out
    assert "anchor_hit" in out and "4/8 = 50%" in out


def test_unstable_cases_are_listed():
    from src.reporting.summary import summarise
    run = results.Run(agent="a", suite="s", reps=3, cases=[
        results.CaseResult(case_id="KA_1", rep=i, results=[results.Result("anchor_hit", "check", status)])
        for i, status in enumerate([results.PASS, results.FAIL, results.PASS])])
    row = summarise([run])[0]
    assert row["rate"] == round(2 / 3, 4) and row["unstable"] == {"KA_1": "2/3"}


def test_verdict_notes_a_changed_judge_temperature(outputs):
    """Scores at different judge temperatures aren't comparable: the verdict says so on judge rows."""
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=PASSING)
    assert run.judge_temperature is None                   # no judges ran
    run.cases[0].results.append(results.Result("faithfulness", "judge", results.PASS, score=0.9, threshold=0.7,
                                               engine="pegasus"))
    run.judge_temperature = 0.7
    save_baseline(run)
    run.judge_temperature = 0.0
    _, rows, baseline = compare(run)
    assert baseline["judge_temperature"] == 0.7
    judge_row = next(r for r in rows if "judge:faithfulness" in r["result"])
    assert "judge temperature changed 0.7 -> 0.0" in judge_row["note"]
    assert all(not r["note"] for r in rows if ":: check:" in r["result"])
    assert load_run(run.run_id).kind == "baseline"         # save_baseline marks (and re-saves) its run


def test_baseline_keeps_the_full_run_and_the_verdict_keeps_both(outputs):
    """The dashboard's verdict view needs both builds case by case, on any machine, later too."""
    from src.verdict.baseline import baseline_run_path, load_baseline_run
    from src.verdict.compare import save_verdict

    stable = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.4.0", case_ids=PASSING)
    save_baseline(stable)
    assert baseline_run_path("knowledge_agent", "sanity").is_file()
    copy = load_baseline_run("knowledge_agent", "sanity")
    assert (copy.build, copy.kind, copy.cases[0].case_id) == ("1.4.0", "baseline", "TC_002")

    new = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.5.0", case_ids=PASSING)
    new.cases[0].results[0].status = results.FAIL            # a regression
    passed, rows, baseline = compare(new)
    path = save_verdict(new, passed, rows, baseline, targets_met=True)
    saved = json.loads(path.read_text())
    assert saved["passed"] is False and saved["baseline"]["build"] == "1.4.0" and saved["has_baseline_run"]
    assert any(r["status"] == "regression" for r in saved["rows"])
    assert load_run(new.run_id).kind == "verdict"
    frozen = load_run(str(new.folder / "baseline_results.json"))
    assert frozen.build == "1.4.0"                           # the baseline as it was at verdict time

    baseline_run_path("knowledge_agent", "sanity").unlink()   # a baseline saved before .run.json existed:
    assert load_baseline_run("knowledge_agent", "sanity").build == "1.4.0"   # found via outputs/runs
