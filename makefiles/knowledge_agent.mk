# knowledge_agent test targets (live ADK).

.PHONY: test-ka-sanity test-ka-sanity-judges test-ka-stage1 test-ka demo-e2e dashboard \
	synth-ka-generate synth-ka-generate-fixture synth-ka-run

test-ka-sanity:
	pytest tests/knowledge_agent/test_sanity.py -v -s

# Live capture + CORTEX DeepEval judges (relevance) → outputs/dashboard
test-ka-sanity-judges:
	RUN_JUDGES=1 pytest tests/knowledge_agent/test_sanity.py -v -s

test-ka-stage1:
	pytest tests/knowledge_agent/test_stage1_eval.py -v -s

test-ka:
	pytest tests/knowledge_agent/ -v

# Synthesizer: Athena → clean → DeepEval goldens (live Athena + CORTEX)
synth-ka-generate:
	python -m src.synth --agent knowledge_agent --mode generate

# Same generate path using repo fixture 8708-response.json (no Athena call)
synth-ka-generate-fixture:
	python -m src.synth --agent knowledge_agent --mode generate --fixture

# Run generated goldens against live KA (+ judges per YAML run.run_judges)
synth-ka-run:
	python -m src.synth --agent knowledge_agent --mode run

demo-e2e: test-ka-sanity

dashboard:
	streamlit run scripts/dashboard_app.py
