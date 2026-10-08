"""The verdict dashboard's data: per-case changes, what changed in words, per-metric comparison, headline."""

from src.core import results
from src.reporting import verdict_view as vv
from src.runners.suite_runner import run_suite
from src.verdict.baseline import save_baseline
from src.verdict.compare import compare, save_verdict


def row(case, name, status, before=None, after=None, note=""):
    return {"result": f"{case} :: {name}", "status": status, "baseline": before, "current": after, "note": note}


def test_case_changes_rank_regressed_over_improved_and_group_by_case():
    rows = [
        row("A", "judge:correctness", "regression", {"pass_rate": 1, "mean_score": 0.86, "n": 1},
            {"pass_rate": 0, "mean_score": 0.55, "n": 1}),
        row("A", "check:anchor_hit", "improved", {"pass_rate": 0, "mean_score": None, "n": 1},
            {"pass_rate": 1, "mean_score": None, "n": 1}),
        row("B", "check:anchor_hit", "ok", {"pass_rate": 1, "mean_score": None, "n": 1},
            {"pass_rate": 1, "mean_score": None, "n": 1}),
        row("C", "judge:relevance", "missing", {"pass_rate": 1, "mean_score": 0.9, "n": 1}, None),
        row("D", "judge:relevance", "new", None, {"pass_rate": 1, "mean_score": 0.9, "n": 1}),
    ]
    changes = vv.case_changes(rows)
    assert {k: c.change for k, c in changes.items()} == {"A": "regressed", "B": "unchanged", "C": "missing",
                                                          "D": "new"}
    assert [i["status"] for i in changes["A"].items] == ["regression", "improved"]       # worst first
    assert changes["B"].items == [] and changes["B"].results == ["check:anchor_hit"]
    assert vv.describe(changes["A"].items[0]) == "correctness 0.86 → 0.55"               # judges: mean score
    assert vv.describe(changes["A"].items[1]) == "anchor hit fail → pass"                 # 1 rep: pass / fail
    assert vv.describe(changes["C"].items[0]) == "relevance: not run this time"
    many = row("E", "check:within_60s", "regression", {"pass_rate": 1.0, "n": 5}, {"pass_rate": 0.6, "n": 5})
    assert vv.describe(vv.case_changes([many])["E"].items[0]) == "within 60s 100% → 60%"   # reps: rates


def test_headline_says_why_in_one_line():
    changes = vv.case_changes([row("A", "judge:x", "regression"), row("B", "judge:x", "improved")])
    assert vv.headline({}, changes, errors=1, targets_missed=2) == (
        "1 test case regressed · 1 could not be evaluated · 2 release targets missed · 1 improved")
    calm = vv.case_changes([row("A", "judge:x", "ok")])
    assert vv.headline({"targets_met": True}, calm, 0, 0) == "no regressions against the baseline · all release " \
                                                            "targets met"


def test_a_saved_verdict_loads_with_both_builds(outputs):
    stable = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.4.0", case_ids=["TC_002"])
    save_baseline(stable)
    new = run_suite("knowledge_agent", "sanity", offline=True, judges=False, build="1.5.0", case_ids=["TC_002"])
    assert vv.load(new) is None                                       # an ordinary run is not a verdict
    new.cases[0].results[0].status = results.FAIL
    passed, rows, baseline = compare(new)
    save_verdict(new, passed, rows, baseline, targets_met=True)
    verdict = vv.load(new)
    assert not verdict.passed and verdict.baseline_build == "1.4.0" and verdict.baseline_run.build == "1.4.0"
    metrics = {m["name"]: m for m in vv.metric_changes(verdict.baseline_run, new)}
    assert metrics["answer_non_empty"]["baseline_rate"] == 1.0 and metrics["answer_non_empty"]["current_rate"] == 0.0
    assert vv.case_changes(verdict.outcome["rows"])["TC_002"].change == "regressed"
