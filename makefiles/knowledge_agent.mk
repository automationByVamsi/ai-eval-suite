# knowledge_agent test targets (live ADK).

.PHONY: test-ka-sanity test-ka-sanity-judges test-ka demo-e2e dashboard \
	synth-ka-prepare synth-ka-prepare-fixture synth-ka-generate

test-ka-sanity:
	pytest tests/knowledge_agent/test_sanity.py -v -s

# Live capture + CORTEX DeepEval judges (relevance) → outputs/dashboard
test-ka-sanity-judges:
	RUN_JUDGES=1 pytest tests/knowledge_agent/test_sanity.py -v -s

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
