# knowledge_agent test targets (live ADK).

.PHONY: test-ka-sanity test-ka-sanity-judges test-ka-stage1 test-ka demo-e2e dashboard

test-ka-sanity:
	pytest tests/knowledge_agent/test_sanity.py -v -s

# Live capture + CORTEX DeepEval judges (relevance)
test-ka-sanity-judges:
	RUN_JUDGES=1 pytest tests/knowledge_agent/test_sanity.py -v -s

test-ka-stage1:
	pytest tests/knowledge_agent/test_stage1_eval.py -v -s

test-ka:
	pytest tests/knowledge_agent/ -v

demo-e2e: test-ka-sanity

dashboard:
	streamlit run scripts/dashboard_app.py
