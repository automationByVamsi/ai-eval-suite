# knowledge_agent test targets. Add a new stage's targets here as it's built -
# nothing outside this file needs to change.

.PHONY: test-ka-stage1-det test-ka-det test-ka-judge test-ka demo-cache demo-incremental demo-refresh

# --- Stage 1: Query Rewrite ---
test-ka-stage1-det:
	pytest tests/knowledge_agent/test_stage1_deterministic.py tests/knowledge_agent/test_stage1_fields_deterministic.py -v

# test-ka-stage1-judge: added once tests/knowledge_agent/test_stage1_judge.py exists

# --- Stage 2: Anchor Node Identification (next up) ---
# test-ka-stage2-det / test-ka-stage2-judge: added once those test files exist

# --- Aggregates: run across every stage that exists so far ---
test-ka-det:
	pytest tests/knowledge_agent -k deterministic -v

test-ka-judge:
	pytest tests/knowledge_agent -k judge -v

test-ka:
	pytest tests/knowledge_agent -v

# --- Leadership demo: trigger agent -> capture -> validate -> dashboard ---
# -s so the printed progress/summary is visible, not swallowed by pytest.
demo-cache:
	DEMO_MODE=cache pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s

demo-incremental:
	DEMO_MODE=incremental pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s

demo-refresh:
	DEMO_MODE=refresh pytest tests/knowledge_agent/test_demo_end_to_end.py -v -s
