"""Release targets, consistency across repetitions (HIVE-6165), new check options, SME calibration."""

import zipfile

from conftest import ROOT
from streamlit.testing.v1 import AppTest

from src.core.results import CaseResult, Result, Run
from src.fields import checks
from src.reporting import release
from src.reporting.calibration import calibrate, review_sheet
from src.runners.suite_runner import run_suite


def _case(case_id, rep, evidence, correctness="pass", score=0.9, error=""):
    """One case result with a correctness judge and a passing within_60s check."""
    return CaseResult(case_id, rep=rep, error=error, details={"evidence_page_ids": evidence}, results=[
        Result("correctness", "judge", correctness, score=score, threshold=0.7),
        Result("within_60s", "check", "pass"),
    ])


def _run(cases, reps=1, targets=None):
    """A golden run of `cases`, with a consistency rule on evidence pages."""
    return Run("knowledge_agent", "golden", reps=reps, cases=cases, targets=targets or {},
               consistency={"same": "evidence_page_ids", "min_overlap": 1.0, "all_pass": ["correctness"]})


# --- targets: pass rates across the run ------------------------------------------------------------

def test_targets_met_missed_and_no_data():
    cases = [_case(f"C{i}", 0, ["1"], "pass" if i < 9 else "fail") for i in range(10)]
    run = _run(cases, targets={"correctness": 0.9, "within_60s": 1.0, "faithfulness": 0.95, "error_rate": 0.05})
    rows = {r["name"]: r for r in release.targets(run)}
    assert rows["correctness"]["met"] is True and rows["correctness"]["actual"] == 0.9
    assert rows["within_60s"]["met"] is True
    assert rows["faithfulness"]["met"] is False and "no result" in rows["faithfulness"]["detail"]   # no data = missed
    assert rows["error_rate"]["met"] is True and rows["error_rate"]["ceiling"]
    passed, _ = release.gate(run)
    assert not passed


def test_error_rate_is_a_ceiling():
    cases = [_case("A", 0, ["1"]), _case("B", 0, ["1"], error="agent: timeout")]
    rows = {r["name"]: r for r in release.targets(_run(cases, targets={"error_rate": 0.05}))}
    assert rows["error_rate"]["actual"] == 0.5 and rows["error_rate"]["met"] is False


# --- consistency (HIVE-6165) ----------------------------------------------------------------------

def test_consistent_only_if_same_sources_and_every_rep_passes():
    cases = [
        _case("STABLE", 0, ["40345", "40015"]), _case("STABLE", 1, ["40015", "40345"]),
        _case("STABLE", 2, ["40345", "40015"]),
        _case("DRIFT", 0, ["40345"]), _case("DRIFT", 1, ["40017"]), _case("DRIFT", 2, ["40345"]),
        _case("FLAKY", 0, ["1"]), _case("FLAKY", 1, ["1"], "fail", 0.5), _case("FLAKY", 2, ["1"]),
    ]
    run = _run(cases, reps=3, targets={"consistency": 1.0})
    rows = {r["case"]: r for r in release.consistency(run)}
    assert rows["STABLE"]["consistent"] and rows["STABLE"]["overlap"] == 1.0   # order doesn't matter
    assert not rows["DRIFT"]["consistent"] and "evidence pages changed between runs" in rows["DRIFT"]["why"]
    assert not rows["FLAKY"]["consistent"] and rows["FLAKY"]["passes"]["correctness"] == "2/3"
    assert "correctness passed 2 of 3 runs" in rows["FLAKY"]["why"]
    assert [r["consistent"] for r in release.consistency(run)][0] is False          # inconsistent cases first
    target = release.targets(run)[0]
    assert target["actual"] == 1 / 3 and target["met"] is False


def _rep(rep, anchors, expanded, cited, correctness="pass", expected_answer=True):
    """One repetition of TC_012 with the given anchor, expanded and cited page ids."""
    judge = (Result("correctness", "judge", correctness, score=0.9, threshold=0.7) if expected_answer else
             Result("correctness", "judge", "skip", reason="skipped: case has no expected_answer"))
    return CaseResult("TC_012", rep=rep, answer=f"answer {rep}", question="q", results=[judge], details={
        "anchor_page_ids": anchors, "expanded_page_ids": expanded, "cited_page_ids": cited,
        "evidence_page_ids": anchors + expanded, "evidence_titles": [f"Title {p}" for p in anchors + expanded]})


KA_RULE = {"same": "anchor_page_ids", "min_overlap": 1.0, "all_pass": ["correctness"],
           "report": ["cited_page_ids", "expanded_page_ids"]}


def test_consistency_gates_on_anchor_pages_and_only_reports_cited_and_expanded():
    reps = [_rep(0, ["48822"], ["7282"], ["48822"]), _rep(1, ["48822"], ["9375"], ["48822", "9375"]),
            _rep(2, ["48822"], [], ["48822"])]
    run = Run("knowledge_agent", "sanity", reps=3, cases=reps, consistency=KA_RULE)
    [row] = release.consistency(run)
    assert row["consistent"] and row["overlap"] == 1.0                # same anchor: expansion may vary
    assert row["also"]["expanded_page_ids"] == 0.0 and row["also"]["cited_page_ids"] == 0.5

    reps[1].details["anchor_page_ids"] = ["48875"]
    [row] = release.consistency(Run("knowledge_agent", "sanity", reps=3, cases=reps, consistency=KA_RULE))
    assert not row["consistent"] and row["why"] == "anchor pages changed between runs (0% in common)"


def test_consistency_says_when_a_judge_could_not_run():
    reps = [_rep(n, ["1"], [], ["1"], expected_answer=False) for n in range(3)]
    [row] = release.consistency(Run("knowledge_agent", "sanity", reps=3, cases=reps, consistency=KA_RULE))
    assert row["consistent"] and row["passes"] == {}
    assert row["not_judged"] == {"correctness": "case has no expected_answer"}


def test_pages_by_run_grid():
    from src.reporting import dashboard_parts as ui
    reps = [_rep(0, ["48822"], ["7282"], ["48822"]), _rep(1, ["48875"], [], ["48875"])]
    rows = {r["id"]: r for r in ui.pages_by_run(reps)}
    assert rows["48822"]["runs"] == [["anchor", "cited"], []] and rows["48822"]["differs"]
    assert rows["7282"]["runs"] == [["expanded"], []] and rows["7282"]["title"] == "Title 7282"
    assert "not used" in ui.pages_grid_html(list(rows.values()), 2)


def test_consistency_target_is_not_applicable_with_one_rep():
    run = _run([_case("A", 0, ["1"])], reps=1, targets={"consistency": 1.0})
    [row] = release.targets(run)
    assert row["met"] is None and "more than one run" in row["detail"]
    assert release.gate(run)[0] is True


# --- new check options -------------------------------------------------------------------------------

def test_precision_and_recall_at_k_on_logged_search_candidates():
    spec = {"type": "recall", "k": 3, "threshold": 1.0,
            "compare": [{"field": "search_candidates", "expected": "expected_anchor_page_ids"}]}
    checks.validate({"r": spec}, "test")
    fields = {"search_candidates": ["40346", "40345", "40011", "40017"]}
    def recall(anchor):
        return checks.run_checks({"r": spec}, fields, {"expected": {"expected_anchor_page_ids": [anchor]}})[0].status

    assert recall("40345") == "pass"         # in the top 3 logged candidates
    assert recall("40017") == "fail"         # logged 4th: outside k

    spec = {"type": "precision", "k": 2, "threshold": 0,
            "compare": [{"field": "search_candidates",
                         "expected": ["expected_anchor_page_ids", "expected_related_page_ids"]}]}
    [result] = checks.run_checks({"p": spec}, fields, {"expected": {"expected_anchor_page_ids": ["40345"],
                                                                    "expected_related_page_ids": ["40346"]}})
    assert result.score == 1.0 and result.status == "pass"


def test_ndcg_matches_ranx_on_the_tc_002_search():
    # Expected values come from ranx ndcg@5 on TC_002's search results.
    assert checks.ndcg(["40346", "40345", "40011"], ["40345"]) == 0.6309
    assert checks.ndcg(["40346", "40345", "40011"], ["40345", "40017"]) == 0.3869
    assert checks.ndcg(["40022", "40015"], ["40015", "40022"]) == 1.0
    assert checks.ndcg(["40346"], ["40345"]) == 0.0
    assert checks.ndcg(["1", "2", "3", "4", "5", "6"], ["6"], k=5) == 0.0          # below the top 5


def test_ndcg_check_merges_one_ranked_list_per_search():
    spec = {"type": "ndcg", "k": 5, "threshold": 0.7,
            "compare": [{"field": "search_ranked", "expected": "expected_anchor_page_ids"}]}
    checks.validate({"n": spec}, "test")
    def run(ranked, gold):
        case = {"expected": {"expected_anchor_page_ids": gold}}
        return checks.run_checks({"n": spec}, {"search_ranked": ranked}, case)[0]

    tc_002 = run([["40346", "40345", "40011"]], ["40345"])
    assert (tc_002.status, tc_002.score, tc_002.threshold) == ("fail", 0.6309, 0.7)
    assert "{'40345': 2}" in tc_002.reason                                    # where the gold page was
    tc_012 = run([["40022"], ["40015"]], ["40015"])                          # two searches: 1st in the 2nd one
    assert (tc_012.status, tc_012.score) == ("pass", 1.0)
    both = run([["40022", "40099"], ["40015", "40022"]], ["40015", "40099"])  # 1st in one search, 2nd in other
    assert both.score == round((1 + 0.6309) / 1.6309, 4)
    assert run([["40346"]], []).status == "skip"                             # no gold pages: skipped
    assert checks._positions([["a", "b"], ["c", "a"]]) == {"a": 1, "c": 1, "b": 2}   # best position in any


def test_a_diagnostic_check_is_shown_but_does_not_fail_the_case():
    spec = {"type": "any_in", "field": "anchor_page_ids", "expected": "expected_anchor_page_ids", "diagnostic": True}
    checks.validate({"anchor_hit": spec}, "test")
    [miss] = checks.run_checks({"anchor_hit": spec}, {"anchor_page_ids": ["40346"]},
                               {"expected": {"expected_anchor_page_ids": ["40345"]}})
    assert miss.status == "fail" and miss.diagnostic
    good_answer = CaseResult("TC", results=[Result("correctness", "judge", "pass", score=0.9, threshold=0.7), miss])
    assert good_answer.status == "pass"                                      # the answer was right
    bad_answer = CaseResult("TC", results=[Result("correctness", "judge", "fail", score=0.2, threshold=0.7), miss])
    assert bad_answer.status == "fail"


def test_when_can_read_the_test_cases_expected_block():
    spec = {"type": "present", "field": "disclosures", "when": {"expected": "should_decline", "is": True}}
    decline = {"expected": {"should_decline": True}}
    assert checks.run_checks({"w": spec}, {"disclosures": []}, decline)[0].status == "fail"
    assert checks.run_checks({"w": spec}, {"disclosures": ["Not in the knowledge base"]}, decline)[0].status == "pass"
    assert checks.run_checks({"w": spec}, {"disclosures": []}, {"expected": {}})[0].status == "skip"


def test_present_over_several_fields():
    spec = {"type": "present", "fields": ["a", "b"]}
    assert checks.run_checks({"p": spec}, {"a": "x", "b": "y"}, {})[0].status == "pass"
    result = checks.run_checks({"p": spec}, {"a": "x", "b": ""}, {})[0]
    assert result.status == "fail" and "b empty" in result.reason


def test_knowledge_agent_suites_load_with_targets_and_new_checks(outputs):
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False, case_ids=["TC_002"])
    names = {r.name: r.status for r in run.cases[0].results}
    assert names["within_60s"] == "pass" and names["page_link_for_every_source"] == "pass"
    assert names["citations_in_evidence_set"] == "pass"
    assert names["caveat_when_not_high"] == "skip"                        # confidence is HIGH
    assert run.targets == {"case_pass_rate": 1.0, "error_rate": 0.05}


# --- SME calibration ---------------------------------------------------------------------------------

def test_review_sheet_and_calibration(tmp_path):
    from src.exporters.xlsx import Sheet, write_xlsx
    from src.importers.spreadsheet import read_rows
    cases = [CaseResult(f"C{i}", question="q", answer="a", results=[
        Result("correctness", "judge", "pass" if s >= 0.7 else "fail", score=s, threshold=0.7),
        Result("anchor_hit", "check", "fail", diagnostic=True), Result("within_60s", "check", "pass")])
        for i, s in enumerate([0.95, 0.9, 0.75, 0.72, 0.4, 0.3])]
    cases[0].input = {"question": "q", "question_type": "how", "business_area": "Business Banking"}
    cases[0].details = {"search_candidates": ["1", "2"], "confidence": "high",
                        "anchor_pages": [{"page_id": "1", "title": "Add a need", "uri_ui": "https://kb/1"}]}
    columns = {"Pages search found": "search_candidates", "Anchor pages": "anchor_pages"}
    sheet = review_sheet(_run(cases), tmp_path / "review.xlsx", columns)
    rows = read_rows(sheet, sheet="Review", header_row=2)
    first = rows[0]
    assert (first["Query type"], first["Business area"], first["Confidence"]) == ("how", "Business Banking", "HIGH")
    assert first["Correctness (pass ≥ 0.7)"] == "0.95" and first["SME verdict (pass / fail)"] == ""
    assert first["Pages search found"] == "1\n2"                       # one item per line
    assert first["Anchor pages"] == "1 | Add a need | https://kb/1"     # id | title | link
    assert first["Deterministic checks"] == "1/2 passed\nFailed: Anchor hit (diagnostic)"
    assert rows[1]["Anchor pages"] == ""                               # a case without the field: empty cell
    assert "How to review" in zipfile.ZipFile(sheet).read("xl/workbook.xml").decode()

    # The SME fills the verdicts (0.75 and 0.72 aren't good enough), saved as the same workbook.
    headers = [h for h in first if h != "_row"]
    for row, sme in zip(rows, ["pass", "pass", "fail", "fail", "fail", "fail"], strict=True):
        row["SME verdict (pass / fail)"] = sme
    marked = write_xlsx(tmp_path / "marked.xlsx", [Sheet("Review", [("Band", h) for h in headers],
                                                         [[r[h] for h in headers] for r in rows])])
    [report] = calibrate(marked)
    assert report["judge"] == "correctness" and report["threshold"] == 0.7
    assert report["n"] == 6 and report["false_pass"] == 2 and report["false_fail"] == 0
    assert round(report["agreement"], 2) == 0.67
    assert 0.75 < report["best_threshold"] <= 0.9 and report["best_agreement"] == 1.0


def test_calibrate_says_why_there_is_nothing_to_compare(tmp_path):
    from src.reporting.calibration import why_empty
    no_judges = review_sheet(_run([CaseResult("C1", question="q", answer="a")]), tmp_path / "no_judges.xlsx")
    assert "made without judges" in why_empty(no_judges)
    unmarked = review_sheet(_run([CaseResult("C1", question="q", answer="a", results=[
        Result("correctness", "judge", "pass", score=0.9, threshold=0.7)])]), tmp_path / "unmarked.xlsx")
    assert calibrate(unmarked) == [] and "no row has an SME verdict" in why_empty(unmarked)


def test_calibrate_still_reads_an_old_csv_review_sheet(tmp_path):
    old = tmp_path / "old.csv"
    old.write_text("case_id,correctness_score,correctness_threshold,sme_verdict\n"
                   "C1,0.9,0.7,pass\nC2,0.8,0.7,fail\nC3,0.3,0.7,fail\n")
    [report] = calibrate(old)
    assert (report["n"], report["false_pass"], report["false_fail"]) == (3, 1, 0)


# --- dashboard ---------------------------------------------------------------------------------------

def test_dashboard_shows_targets_and_consistency(outputs):
    cases = [_rep(0, ["48822"], ["7282"], ["48822"]), _rep(1, ["48875"], [], ["48875"])]
    run = Run("knowledge_agent", "sanity", reps=2, cases=cases, targets={"correctness": 0.9, "consistency": 1.0},
              consistency=KA_RULE)
    run.save()
    app = AppTest.from_file(str(ROOT / "src/reporting/dashboard.py"), default_timeout=60).run()
    assert not app.exception, app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "Release targets" in text and "Consistency over 2 runs" in text
    assert "anchor pages changed between runs" in text
    assert "agent.yaml" not in text and "HIVE" not in text                   # no config talk for readers
    assert any("Consistency" in t.label for t in app.tabs)
    assert "Pages used in each run" in text and "Title 7282" in text and "answer 1" in text
