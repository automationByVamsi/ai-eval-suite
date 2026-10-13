# Every day-to-day command; `make help` lists them all. Examples:
#   make run      AGENT=knowledge_agent SUITE=sanity [OFFLINE=1]   (OFFLINE=1 reuses saved traces)
#   make baseline AGENT=knowledge_agent SUITE=sanity BUILD=1.4.0 REPS=5
#   make verdict  AGENT=knowledge_agent SUITE=sanity BUILD=1.5.0 REPS=5

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
FILE ?=
SHEET ?=
MAPPING ?=
DRY_RUN ?=
TRACE ?=
LAST ?= 1

FLAGS = --reps $(REPS) $(if $(METRICS),--metrics $(METRICS)) $(if $(BUILD),--build $(BUILD)) $(if $(OFFLINE),--offline) $(if $(filter 0,$(JUDGES)),--no-judges) \
        $(foreach c,$(CASE),--case $(c))
# Runs in the project's .venv, or in your activated virtual env. --frozen: never re-resolve uv.lock
# (works without access to SAR, where Pegasus lives).
UV_RUN = uv run --frozen $(if $(VIRTUAL_ENV),--active)
EVAL   = $(UV_RUN) python -m src          # the CLI: src/cli.py

.PHONY: help setup cortex-login doctor list new-agent run baseline verdict sources goldens import-cases export-cases fields summary review-sheet calibrate report dashboard test

help:
	@echo "make setup                                  install everything (needs uv), create env/.env"
	@echo "make cortex-login                           CorteX DevKit only: sign in with SSO (once; CORTEX_AUTH=devkit)"
	@echo "make doctor                                 check Python env, Pegasus, env files, certificates, CORTEX"
	@echo "make list                                   agents and suites"
	@echo "make new-agent NAME=.. [INPUT_FIELD=..]     create agents/<NAME>/ from the template"
	@echo "make run      AGENT=.. SUITE=..             run a suite  [OFFLINE=1] [JUDGES=0] [REPS=n] [CASE="TC_001 TC_002"] [METRICS="faithfulness"]"
	@echo "make baseline AGENT=.. SUITE=.. BUILD=..    run a stable build and save it as the baseline [REPS=5]"
	@echo "make verdict  AGENT=.. SUITE=.. BUILD=..    run the new build and compare with the baseline [REPS=5]"
	@echo "make sources  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: fetch source documents into synth/cache"
	@echo "make goldens  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: generate test cases [STYLES='type_how type_why'] [REPLACE=1]"
	@echo "make summary  AGENT=.. SUITE=.. [LAST=10]  pass rate of every check and judge across the last N runs"
	@echo "make fields   AGENT=.. [SUITE=..] [CASE=..] preview the fields.yaml values + checks on saved traces [TRACE=file]"
	@echo "make import-cases AGENT=.. FILE=..          spreadsheet (.xlsx/.csv) -> test case JSON [SHEET=..] [MAPPING=..] [DRY_RUN=1]"
	@echo "make export-cases AGENT=..                  test case JSON -> one Excel workbook, a sheet per suite [SUITE=..] [FILE=..]"
	@echo "make review-sheet AGENT=.. SUITE=.. [RUN=..] Excel of answers, pages + judge scores for SMEs to mark"
	@echo "make report   AGENT=.. SUITE=.. [RUN=..]    one run as a single HTML file to share (the dashboard, offline)"
	@echo "make calibrate FILE=..                      compare the judges with the SME's marks"
	@echo "make dashboard                              open the results dashboard"
	@echo "make test                                   test the framework itself (offline)"

# Installs everything (Pegasus too, if env/.env has your SAR token); steps in scripts/setup.sh.
setup:
	@sh scripts/setup.sh

# CorteX DevKit SSO sign-in (CORTEX_AUTH=devkit only); the token is kept in your OS keyring.
cortex-login:
	$(UV_RUN) cx auth login

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
	$(EVAL) goldens $(AGENT) $(SYNTH) $(if $(STYLES),--styles $(STYLES)) $(if $(REPLACE),--replace)

# Pass rates across the last N saved runs (no agent call, no judges).
summary:
	$(EVAL) summary $(AGENT) $(SUITE) --last $(LAST)

# Preview fields.yaml values and checks on saved traces (no agent call, no judges).
fields:
	$(EVAL) fields $(AGENT) --suite $(SUITE) $(foreach c,$(CASE),--case $(c)) $(if $(TRACE),--trace "$(TRACE)")

# Spreadsheet -> test case JSON, mapped by agents/<AGENT>/importers/<MAPPING>.yaml. Quote FILE if it has spaces.
import-cases:
	@test -n "$(FILE)" || { echo 'Give the spreadsheet: make import-cases AGENT=$(AGENT) FILE="path/to/file.xlsx"'; exit 1; }
	$(EVAL) import-cases $(AGENT) "$(FILE)" $(if $(MAPPING),--mapping $(MAPPING)) $(if $(SHEET),--sheet "$(SHEET)") $(if $(DRY_RUN),--dry-run)

# Test case JSON -> one Excel workbook. All suites unless SUITE= is given; default FILE in outputs/exports/.
export-cases:
	$(EVAL) export-cases $(AGENT) $(if $(filter command line environment,$(origin SUITE)),--suite $(SUITE)) $(if $(FILE),--out "$(FILE)")

# Judge calibration: SMEs mark a run's answers and scores (review-sheet), then compare (calibrate).
review-sheet:
	$(EVAL) review-sheet $(AGENT) $(SUITE) $(if $(RUN),--run $(RUN))

# One run as a single, self-contained HTML file (the dashboard's views, no Streamlit needed to open it).
report:
	$(EVAL) report $(AGENT) $(SUITE) $(if $(RUN),--run $(RUN))

calibrate:
	@test -n "$(FILE)" || { echo 'Give the marked sheet: make calibrate FILE=outputs/review/<run id>.xlsx'; exit 1; }
	$(EVAL) calibrate "$(FILE)"

dashboard:
	$(UV_RUN) streamlit run src/reporting/dashboard.py

test:
	$(UV_RUN) pytest -q
