# knowledge_agent test targets.

.PHONY: test-ka-stage1 test-ka-stage2 test-ka demo-e2e demo-cache demo-incremental demo-refresh dashboard

test-ka-stage1:
	pytest tests/knowledge_agent/test_stage1.py -v -s

test-ka-stage2:
	pytest tests/knowledge_agent/test_stage2.py -v -s

test-ka:
	pytest tests/knowledge_agent/test_stage1.py tests/knowledge_agent/test_stage2.py -v

# Leadership / walkthrough: all registered stages → dashboard
demo-e2e:
	DEMO_MODE=cache pytest tests/knowledge_agent/test_demo_e2e.py -v -s

demo-cache:
	DEMO_MODE=cache pytest tests/knowledge_agent/test_demo_e2e.py -v -s

demo-incremental:
	DEMO_MODE=incremental pytest tests/knowledge_agent/test_demo_e2e.py -v -s

demo-refresh:
	DEMO_MODE=refresh pytest tests/knowledge_agent/test_demo_e2e.py -v -s

dashboard:
	streamlit run scripts/dashboard_app.py
