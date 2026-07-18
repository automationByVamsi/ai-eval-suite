"""Plain-text summary table. No extra dependency on purpose - easy for anyone to read or extend."""

from src.models.evaluation_result import EvaluationResult


def print_dashboard(results: list[EvaluationResult]) -> None:
    total = len(results)
    passed = sum(r.passed for r in results)

    print("\n" + "=" * 60)
    print(f"EVALUATION SUMMARY: {passed}/{total} passed")
    print("=" * 60)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.test_case_id} ({r.agent_name})")
        if not r.passed:
            for reason in r.failed_reasons:
                print(f"           - {reason}")
    print("=" * 60 + "\n")
