# Front door for running the eval suite - `make <target>`, like `npm run <script>`.
# Each agent owns its own targets in makefiles/<agent>.mk - this file only
# holds things that span every agent, so onboarding a new agent never
# requires touching this file.

include $(wildcard makefiles/*.mk)

.PHONY: test-all help new-agent

test-all:
	pytest -v

# Scaffold a minimal agent pack: make new-agent name=my_agent
# Optional: MESSAGE_FIELD=complaint_ref  or  PEGASUS=0
name ?=
MESSAGE_FIELD ?= question
PEGASUS ?= 1

new-agent:
	@if [ -z "$(name)" ]; then echo "Usage: make new-agent name=my_agent"; exit 1; fi
	@if [ "$(PEGASUS)" = "0" ]; then \
		python3 scripts/new_agent.py --name "$(name)" --message-field "$(MESSAGE_FIELD)" --no-pegasus; \
	else \
		python3 scripts/new_agent.py --name "$(name)" --message-field "$(MESSAGE_FIELD)"; \
	fi

help:
	@echo "Available targets:"
	@grep -hE '^[a-zA-Z0-9_-]+:' $(MAKEFILE_LIST) | cut -d: -f1 | sort -u | sed 's/^/  make /'
	@echo ""
	@echo "Onboard a new agent:"
	@echo "  make new-agent name=my_agent"
	@echo "  make new-agent name=my_agent MESSAGE_FIELD=complaint_ref PEGASUS=0"
