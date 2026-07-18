# Front door for running the eval suite - `make <target>`, like `npm run <script>`.
# Each agent owns its own targets in makefiles/<agent>.mk - this file only
# holds things that span every agent, so onboarding a new agent never
# requires touching this file.

include $(wildcard makefiles/*.mk)

.PHONY: test-all help

test-all:
	pytest -v

help:
	@echo "Available targets:"
	@grep -hE '^[a-zA-Z0-9_-]+:' $(MAKEFILE_LIST) | cut -d: -f1 | sort -u | sed 's/^/  make /'
