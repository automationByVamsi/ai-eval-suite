# fact_find_workflow test targets.

.PHONY: test-ff-gate test-ff-summary test-ff demo-ff-e2e demo-ff-cache generate-ff-payloads

test-ff-gate:
	DEMO_MODE=cache pytest tests/fact_find_workflow/test_gate_validation.py -v -s

test-ff-summary:
	DEMO_MODE=cache pytest tests/fact_find_workflow/test_summary_vs_aggregate.py -v -s

test-ff:
	DEMO_MODE=cache pytest tests/fact_find_workflow/test_gate_validation.py tests/fact_find_workflow/test_summary_vs_aggregate.py -v

demo-ff-e2e:
	DEMO_MODE=cache pytest tests/fact_find_workflow/test_demo_e2e.py -v -s

demo-ff-cache:
	DEMO_MODE=cache pytest tests/fact_find_workflow/test_demo_e2e.py -v -s

# Ground truth: call ICA / Counter / OCIS APIs → aggregated_payloads/{ref}.json
generate-ff-payloads:
	python3 -m scripts.generate_factfind_payloads

# Back-compat aliases
test-ff-stage1: test-ff-gate
test-ff-stage2: test-ff-summary
