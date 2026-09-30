# Everything you need day to day. `make help` lists it.
#
#   make run      AGENT=knowledge_agent SUITE=sanity
#   make run      AGENT=knowledge_agent SUITE=sanity OFFLINE=1        (reuse saved traces)
#   make baseline AGENT=knowledge_agent SUITE=sanity BUILD=1.4.0 REPS=5
#   make verdict  AGENT=knowledge_agent SUITE=sanity BUILD=1.5.0 REPS=5
#   make new-agent NAME=my_agent INPUT_FIELD=question
#   make sources  AGENT=knowledge_agent [GROUP="Recoveries Commercial Bank"] [IDS="36626 39696"]
#   make goldens  AGENT=knowledge_agent [GROUP=..] [IDS=..] [REPLACE=1]     (synthesizer)

AGENT ?= knowledge_agent
SUITE ?= sanity
REPS  ?= 1
BUILD ?=
OFFLINE ?=
JUDGES ?= 1
NAME ?=
INPUT_FIELD ?= question
CASE ?=
IDS ?=
GROUP ?=
REPLACE ?=

FLAGS = --reps $(REPS) $(if $(BUILD),--build $(BUILD)) $(if $(OFFLINE),--offline) $(if $(filter 0,$(JUDGES)),--no-judges) \
        $(foreach c,$(CASE),--case $(c))
# Which Python runs the commands: the project's .venv (made by make setup), or — if you activated a
# virtual env first — that one. --frozen: use uv.lock as it is, never re-resolve (so commands work
# even on machines that can't reach SAR, where Pegasus lives).
UV_RUN = uv run --frozen $(if $(VIRTUAL_ENV),--active)
EVAL   = $(UV_RUN) python -m src          # the CLI: src/cli.py

.PHONY: help setup doctor list new-agent run baseline verdict sources goldens dashboard test

help:
	@echo "make setup                                  install everything (needs uv), create env/.env"
	@echo "make doctor                                 check Python env, Pegasus, env files, certificates, CORTEX"
	@echo "make list                                   agents and suites"
	@echo "make new-agent NAME=.. [INPUT_FIELD=..]     create agents/<NAME>/ from the template"
	@echo "make run      AGENT=.. SUITE=..             run a suite  [OFFLINE=1] [JUDGES=0] [REPS=n] [CASE="TC_001 TC_002"]"
	@echo "make baseline AGENT=.. SUITE=.. BUILD=..    run a stable build and save it as the baseline [REPS=5]"
	@echo "make verdict  AGENT=.. SUITE=.. BUILD=..    run the new build and compare with the baseline [REPS=5]"
	@echo "make sources  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: fetch source documents into synth/cache"
	@echo "make goldens  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: generate test cases [REPLACE=1]"
	@echo "make dashboard                              open the results dashboard"
	@echo "make test                                   test the framework itself (offline)"

# Installs everything, including Pegasus when SAR is reachable with your token (see README: Pegasus).
# Without SAR access it still installs everything else; Pegasus metrics then run on DeepEval.
# --inexact: never remove packages that are already installed (e.g. Pegasus installed another way).
setup:
	@if uv sync --inexact --group pegasus; then \
		echo "Installed everything, including Pegasus."; \
	else \
		echo ""; \
		echo "WARNING: Pegasus could not be installed (no SAR access or token - see README: Pegasus)."; \
		echo "Installing everything else. Pegasus metrics will run on DeepEval until Pegasus is installed."; \
		echo ""; \
		uv sync --inexact --frozen; \
	fi
	@test -f env/.env || (cp env/.env.example env/.env && echo "Created env/.env - fill in your values")

doctor:
	$(EVAL) doctor

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

SYNTH = $(if $(GROUP),--group "$(GROUP)") $(if $(IDS),--ids $(IDS))

sources:
	$(EVAL) sources $(AGENT) $(SYNTH)

goldens:
	$(EVAL) goldens $(AGENT) $(SYNTH) $(if $(REPLACE),--replace)

dashboard:
	$(UV_RUN) streamlit run src/reporting/dashboard.py

test:
	$(UV_RUN) pytest -q
