# VERDICT — multi-run reliability + baseline regression (any registered agent).
# Capture live ADK outputs first (pytest tests/<agent>/test_sanity.py).
#
#   make verdict-demo AGENT=knowledge_agent
#   make verdict-check AGENT=fact_find_workflow

AGENT ?= knowledge_agent
SUITE ?= sanity
N ?= 5

.PHONY: verdict-baseline verdict-demo verdict-check verdict-judges verdict-dashboard

verdict-baseline:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) --save-baseline --no-compare

# Show usefulness: baseline then simulated regression vs that baseline
verdict-demo:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) --save-baseline --no-compare
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) --simulate-regression

verdict-check:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N)

verdict-judges:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n 3 --judges --save-baseline

verdict-dashboard:
	streamlit run scripts/verdict_dashboard.py
