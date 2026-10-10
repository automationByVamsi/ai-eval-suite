# Everything you need day to day. `make help` lists it.
#
#   make run      AGENT=knowledge_agent SUITE=sanity
#   make run      AGENT=knowledge_agent SUITE=sanity OFFLINE=1        (reuse saved traces)
#   make baseline AGENT=knowledge_agent SUITE=sanity BUILD=1.4.0 REPS=5
#   make verdict  AGENT=knowledge_agent SUITE=sanity BUILD=1.5.0 REPS=5
#   make new-agent NAME=my_agent INPUT_FIELD=question
#   make sources  AGENT=knowledge_agent [GROUP="Recoveries Commercial Bank"] [IDS="36626 39696"]
#   make goldens  AGENT=knowledge_agent [GROUP=..] [IDS=..] [STYLES=..] [REPLACE=1]   (synthesizer)
#   make fields   AGENT=knowledge_agent [SUITE=..] [CASE=..] [TRACE=file]   (what fields.yaml reads from traces)
#   make import-cases AGENT=knowledge_agent FILE="~/Downloads/golden.xlsx" [SHEET=..] [MAPPING=..] [DRY_RUN=1]

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

FLAGS = --reps $(REPS) $(if $(BUILD),--build $(BUILD)) $(if $(OFFLINE),--offline) $(if $(filter 0,$(JUDGES)),--no-judges) \
        $(foreach c,$(CASE),--case $(c))
# Which Python runs the commands: the project's .venv (made by make setup), or — if you activated a
# virtual env first — that one. --frozen: use uv.lock as it is, never re-resolve (so commands work
# even on machines that can't reach SAR, where Pegasus lives).
UV_RUN = uv run --frozen $(if $(VIRTUAL_ENV),--active)
EVAL   = $(UV_RUN) python -m src          # the CLI: src/cli.py

.PHONY: help setup cortex-login gcloud-auth gcloud-auth-check ingestion-cases doctor list new-agent run baseline verdict sources goldens import-cases fields summary review-sheet calibrate dashboard test

help:
	@echo "make setup                                  install everything (needs uv), create env/.env"
	@echo "make cortex-login                           CorteX DevKit only: sign in with SSO (once; CORTEX_AUTH=devkit)"
	@echo "make gcloud-auth                            Google Cloud sign-in (SSO), to read the pipeline's GCS buckets"
	@echo "make ingestion-cases [PER_DOMAIN=n] [DOMAIN=..]  pages per domain in the buckets + one test case per page"
	@echo "make doctor                                 check Python env, Pegasus, env files, certificates, CORTEX"
	@echo "make list                                   agents and suites"
	@echo "make new-agent NAME=.. [INPUT_FIELD=..]     create agents/<NAME>/ from the template"
	@echo "make run      AGENT=.. SUITE=..             run a suite  [OFFLINE=1] [JUDGES=0] [REPS=n] [CASE="TC_001 TC_002"]"
	@echo "make baseline AGENT=.. SUITE=.. BUILD=..    run a stable build and save it as the baseline [REPS=5]"
	@echo "make verdict  AGENT=.. SUITE=.. BUILD=..    run the new build and compare with the baseline [REPS=5]"
	@echo "make sources  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: fetch source documents into synth/cache"
	@echo "make goldens  AGENT=.. [GROUP=..] [IDS=..]  synthesizer: generate test cases [STYLES='type_how type_why'] [REPLACE=1]"
	@echo "make summary  AGENT=.. SUITE=.. [LAST=10]  pass rate of every check and judge across the last N runs"
	@echo "make fields   AGENT=.. [SUITE=..] [CASE=..] preview the fields.yaml values + checks on saved traces [TRACE=file]"
	@echo "make import-cases AGENT=.. FILE=..          spreadsheet (.xlsx/.csv) -> test case JSON [SHEET=..] [MAPPING=..] [DRY_RUN=1]"
	@echo "make review-sheet AGENT=.. SUITE=.. [RUN=..] CSV of answers + judge verdicts for an SME to mark"
	@echo "make calibrate FILE=..                      compare the judges with the SME's marks"
	@echo "make dashboard                              open the results dashboard"
	@echo "make test                                   test the framework itself (offline)"

# Installs everything with uv sync, Pegasus included when env/.env has your SAR token.
# The steps are in scripts/setup.sh (readable, commented).
setup:
	@sh scripts/setup.sh

# CorteX DevKit sign-in (only when CORTEX_AUTH=devkit): opens the browser for SSO, then stores the
# token in your OS keyring. Every command after this reaches CORTEX without an API key.
cortex-login:
	$(UV_RUN) cx auth login

# Google Cloud sign-in (browser SSO): "application default credentials", the same as the agent repos.
# Needed only to read the preprocessing pipeline's buckets (AGENT=knowledge_agent/ingestion).
gcloud-auth:
	gcloud auth application-default login
	@echo "✓ Google ADC configured"

gcloud-auth-check:
	@gcloud auth application-default print-access-token >/dev/null 2>&1 \
		&& echo "✓ Google ADC credentials available" \
		|| (echo "✗ Not signed in to Google Cloud. Run: make gcloud-auth" && exit 1)

# One test case per page the preprocessing pipeline stored (agents/knowledge_agent/ingestion/make_cases.py).
ingestion-cases:
	$(UV_RUN) python -m agents.knowledge_agent.ingestion.make_cases \
		$(if $(PER_DOMAIN),--per-domain $(PER_DOMAIN)) $(if $(DOMAIN),--domain $(DOMAIN))

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

# Rates (e.g. anchor hit rate) across the last N saved runs of a suite — no agent call, no judges.
summary:
	$(EVAL) summary $(AGENT) $(SUITE) --last $(LAST)

# What fields.yaml reads from saved traces (and what the checks make of it). No agent call, no judges.
fields:
	$(EVAL) fields $(AGENT) --suite $(SUITE) $(foreach c,$(CASE),--case $(c)) $(if $(TRACE),--trace "$(TRACE)")

# Spreadsheet -> test case JSON files. The column mapping and case template are per agent:
# agents/<AGENT>/importers/<MAPPING>.yaml. FILE may contain spaces: quote it.
import-cases:
	@test -n "$(FILE)" || { echo 'Give the spreadsheet: make import-cases AGENT=$(AGENT) FILE="path/to/file.xlsx"'; exit 1; }
	$(EVAL) import-cases $(AGENT) "$(FILE)" $(if $(MAPPING),--mapping $(MAPPING)) $(if $(SHEET),--sheet "$(SHEET)") $(if $(DRY_RUN),--dry-run)

# Judge calibration: a CSV of a run's answers + judge verdicts for an SME to mark, then the comparison.
review-sheet:
	$(EVAL) review-sheet $(AGENT) $(SUITE) $(if $(RUN),--run $(RUN))

calibrate:
	@test -n "$(FILE)" || { echo 'Give the marked sheet: make calibrate FILE=outputs/review/<run id>.csv'; exit 1; }
	$(EVAL) calibrate "$(FILE)"

dashboard:
	$(UV_RUN) streamlit run src/reporting/dashboard.py

test:
	$(UV_RUN) pytest -q
