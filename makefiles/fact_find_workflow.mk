# fact_find_workflow test targets.

.PHONY: test-ff-sanity test-ff-sanity-cache test-ff-sanity-judges test-ff \
	demo-ff-e2e generate-ff-payloads

# Live ADK (default)
test-ff-sanity:
	EVAL_MODE=live pytest tests/fact_find_workflow/test_sanity.py -v -s

# Reuse traces under outputs/traces/fact_find_workflow/sanity/
test-ff-sanity-cache:
	EVAL_MODE=cache pytest tests/fact_find_workflow/test_sanity.py -v -s

# Live + CORTEX judges (gate / summary by case path) → outputs/dashboard
test-ff-sanity-judges:
	RUN_JUDGES=true EVAL_MODE=live pytest tests/fact_find_workflow/test_sanity.py -v -s

test-ff:
	pytest tests/fact_find_workflow/test_sanity.py -v

demo-ff-e2e: test-ff-sanity

# Ground truth: call ICA / Counter / OCIS APIs → aggregated_payloads/{ref}.json
generate-ff-payloads:
	python3 -m scripts.generate_factfind_payloads
