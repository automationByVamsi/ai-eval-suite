# fact_find_workflow test targets (live ADK).

.PHONY: test-ff-sanity test-ff demo-ff-e2e generate-ff-payloads

test-ff-sanity:
	pytest tests/fact_find_workflow/test_sanity.py -v -s

test-ff:
	pytest tests/fact_find_workflow/ -v

demo-ff-e2e: test-ff-sanity

# Ground truth: call ICA / Counter / OCIS APIs → aggregated_payloads/{ref}.json
generate-ff-payloads:
	python3 -m scripts.generate_factfind_payloads
