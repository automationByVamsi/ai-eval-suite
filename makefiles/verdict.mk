# VERDICT — live multi-run reliability + baseline regression (any registered agent).
# Each rep: live ADK invoke → deterministic checks + CORTEX judges (needs network + creds).
# Traces land under outputs/traces/.
#
#   make verdict-baseline AGENT=knowledge_agent
#   make verdict-check AGENT=knowledge_agent
#   make verdict-demo AGENT=knowledge_agent
#
# Skip judges (deterministic only): make verdict-check JUDGES=
# Fewer reps when judges on: make verdict-check N=3

AGENT ?= knowledge_agent
SUITE ?= sanity
N ?= 5
# Default: run judges. Set JUDGES= to disable.
JUDGES ?= --judges

.PHONY: verdict-baseline verdict-demo verdict-check verdict-judges verdict-dashboard

verdict-baseline:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) $(JUDGES) --save-baseline --no-compare

# Show usefulness: baseline then simulated regression vs that baseline
verdict-demo:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) $(JUDGES) --save-baseline --no-compare
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) $(JUDGES) --simulate-regression

verdict-check:
	python3 -m scripts.run_verdict --agent $(AGENT) --suite $(SUITE) --n $(N) $(JUDGES)

# Alias kept for clarity / older docs
verdict-judges: verdict-baseline

verdict-dashboard:
	streamlit run scripts/verdict_dashboard.py
