# Fact Find Workflow — agent onboarding notes
#
# Input list: data/fact_find_workflow/complaint-references.json
#   Groups: positive / negative / edge
#   Loader: src/parsers/fact_find_workflow/complaint_refs.py
#
# Ground truth BEFORE agent runs:
#   1. Fill .env.factfind.api (from .env.factfind.api.example)
#   2. Optional APIC mTLS certs under data/fact_find_workflow/certs/
#   3. make generate-ff-payloads
#      → data/fact_find_workflow/aggregated_payloads/{complaintRef}.json
#
# Eval packages (not Knowledge-Agent pipeline stages):
#   gate_validation       — complaint ref format / InvalidComplaintId
#   summary_vs_aggregate  — Customer FactFind Summary vs aggregated payload
#
# Make targets: test-ff-gate, test-ff-summary, test-ff, demo-ff-e2e, generate-ff-payloads
# Metrics: configs/evaluations/fact_find_workflow/METRICS.md
#
# Agent: configs/agents.yaml → fact_find_workflow
# Live vs replay: DEMO_MODE=refresh|cache (AdkClient / ensure_traces)
