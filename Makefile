# Everything you need day to day. `make help` lists it.
#
#   make run      AGENT=knowledge_agent SUITE=sanity
#   make run      AGENT=knowledge_agent SUITE=sanity OFFLINE=1        (reuse saved traces)
#   make baseline AGENT=knowledge_agent SUITE=sanity BUILD=1.4.0 REPS=5
#   make verdict  AGENT=knowledge_agent SUITE=sanity BUILD=1.5.0 REPS=5
#   make new-agent NAME=my_agent INPUT_FIELD=question
#   make sources  AGENT=knowledge_agent IDS="8708 9001"      (synthesizer: fetch documents)
#   make goldens  AGENT=knowledge_agent [REPLACE=1]          (synthesizer: generate test cases)

AGENT ?= knowledge_agent
SUITE ?= sanity
REPS  ?= 1
BUILD ?=
OFFLINE ?=
JUDGES ?= 1
NAME ?=
INPUT_FIELD ?= question
IDS ?=
REPLACE ?=

FLAGS = --reps $(REPS) $(if $(BUILD),--build $(BUILD)) $(if $(OFFLINE),--offline) $(if $(filter 0,$(JUDGES)),--no-judges)
EVAL  = uv run python -m evalkit

.PHONY: help setup list new-agent run baseline verdict sources goldens dashboard test

help:
	@echo "make setup                                  install everything (needs uv)"
	@echo "make list                                   agents and suites"
	@echo "make new-agent NAME=.. [INPUT_FIELD=..]     create agents/<NAME>/ from the template"
	@echo "make run      AGENT=.. SUITE=..             run a suite  [OFFLINE=1] [JUDGES=0] [REPS=n]"
	@echo "make baseline AGENT=.. SUITE=.. BUILD=..    run a stable build and save it as the baseline [REPS=5]"
	@echo "make verdict  AGENT=.. SUITE=.. BUILD=..    run the new build and compare with the baseline [REPS=5]"
	@echo "make sources  AGENT=.. IDS=\"id1 id2\"        synthesizer: fetch source documents"
	@echo "make goldens  AGENT=.. [REPLACE=1]          synthesizer: generate test cases into testdata/golden"
	@echo "make dashboard                              open the results dashboard"
	@echo "make test                                   test the framework itself (offline)"

setup:
	uv sync
	@test -f .env || (cp .env.example .env && echo "Created .env - fill in your values")

list:
	$(EVAL) list

new-agent:
	@test -n "$(NAME)" || (echo "Usage: make new-agent NAME=my_agent [INPUT_FIELD=question]" && exit 1)
	$(EVAL) new-agent $(NAME) --input-field $(INPUT_FIELD)

run:
	$(EVAL) run $(AGENT) $(SUITE) $(FLAGS)

baseline:
	$(EVAL) baseline $(AGENT) $(SUITE) $(FLAGS)

verdict:
	$(EVAL) verdict $(AGENT) $(SUITE) $(FLAGS)

sources:
	@test -n "$(IDS)" || (echo 'Usage: make sources AGENT=knowledge_agent IDS="8708 9001"' && exit 1)
	$(EVAL) sources $(AGENT) $(IDS)

goldens:
	$(EVAL) goldens $(AGENT) $(if $(REPLACE),--replace)

dashboard:
	uv run streamlit run dashboard.py

test:
	uv run pytest -q
