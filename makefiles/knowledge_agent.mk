# knowledge_agent test targets.

.PHONY: test-ka-sanity test-ka-sanity-cache test-ka-sanity-judges test-ka \
	demo-e2e dashboard synth-ka-prepare synth-ka-prepare-fixture synth-ka-generate

# Live ADK (default)
test-ka-sanity:
	EVAL_MODE=live pytest tests/knowledge_agent/test_sanity.py -v -s

# Reuse traces under outputs/traces/knowledge_agent/sanity/
test-ka-sanity-cache:
	EVAL_MODE=cache pytest tests/knowledge_agent/test_sanity.py -v -s

# Live (or set EVAL_MODE=cache) + CORTEX judges → outputs/dashboard
test-ka-sanity-judges:
	RUN_JUDGES=true EVAL_MODE=live pytest tests/knowledge_agent/test_sanity.py -v -s

test-ka:
	pytest tests/knowledge_agent/test_sanity.py -v

# Synthesizer step 1: Athena → cleaned source_docs (like generate-ff-payloads)
synth-ka-prepare:
	python -m src.synth --agent knowledge_agent --prepare --page-id 8708

# Same prepare path using repo fixture (no Athena call)
synth-ka-prepare-fixture:
	python -m src.synth --agent knowledge_agent --prepare --page-id 8708 --fixture 8708-response.json

# Synthesizer step 2: source_docs → DeepEval goldens (needs CORTEX)
synth-ka-generate:
	python -m src.synth --agent knowledge_agent --generate

demo-e2e: test-ka-sanity

dashboard:
	streamlit run scripts/dashboard_app.py
