# Fact Find metrics — why, what, how

Two eval packages. **Deterministic checks** catch hard mismatches first; **judges** catch wording / judgment risks.

Ground truth for the success path = aggregated payload (`data/fact_find_workflow/aggregated_payloads/`), turned into `retrieval_context`.

---

## `gate_validation` — accept / reject the complaint ref

| Metric | Why | Catches | Example fail |
|--------|-----|---------|--------------|
| **validation_message_clarity** (GEval) | Agents must explain format (`NC` + 8 digits), not shrug | Vague or wrong InvalidComplaintId text | Input `please look up NC…` → answer “something went wrong” with no format hint |
| **relevance** | Reply should be about *this* input | Off-topic / wrong-path chatter | Valid `NC10010556` → long FactFind summary when gate should only validate |

---

## `summary_vs_aggregate` — UI summary vs aggregate

### Built-ins (general quality)

| Metric | Why chosen | How it works | Example fail |
|--------|------------|--------------|--------------|
| **faithfulness** | Primary anti-hallucination vs aggregate | Claims in summary must be supported by `retrieval_context` | Summary DOB `19/08/1991` when context says `19/08/1990` |
| **hallucination** | Extra check on invented facts | Summary vs ground-truth context snippets | Invents a Trusted Party when API returned 404 / none |
| **relevance** | Summary should answer the complaint ref task | Input ref ↔ answer about that customer/case | Dumps unrelated product FAQ for `NC10010556` |
| **summarization** | UI is a *summary* of backend facts | Coverage + concision vs source document (aggregate) | Omits Support Needs entirely while repeating fluff |
| **contextual_relevancy** | Aggregate context must be on-topic for the ref | Is retrieved context useful for this complaint? | Wrong party / wrong case blob in context |
| **task_completion** | Did we deliver a usable FactFind? | End-to-end: input → adequate summary | Truncates after profile; no holdings / notes |
| **tool_correctness** | Right backends called | `tools_called` vs `expected_tools` (order optional) | Never calls ICA / holdings tools on success path |
| **mcp_use** | Right MCP tool + args vs catalog | Scores selection against Fact Find MCP catalog | Calls wrong server or bad args for party lookup |
| **mcp_task_completion** | Did MCP usage finish the job? | Wrapped as short conversation (ref → summary + tools) | Tools called but summary still empty / failed |

MCP / tool metrics **auto-skip** when the ADK replay has no tool events. Prefer a live success capture to activate them.

### Domain GEval (Fact Find–specific risks)

Built-ins don’t know bank product rules. These rubrics do:

| Metric | Why | Example fail |
|--------|-----|--------------|
| **support_needs_fidelity** | Vulnerability data — omit/rename is high severity | Context has `Domestic/Financial Abuse`; summary drops it or changes consent |
| **profile_accuracy** | Identity must match OCIS/profile | Wrong name, party ID, address, or marital status |
| **missing_data_honesty** | Failed APIs must not be papered over | Trusted Parties 404 → summary invents “Mrs X as trusted party” |
| **complaint_account_association** | Wrong account = wrong complaint context | Marks a different Classic account as “Associated with complaint” |

---

## How scoring finds issues (mental model)

```
complaint_ref ──► agent answer (UI text)
                      ▲
aggregated payload ───┘  (as retrieval_context / source_document)
```

1. **Deterministic** (contracts): exact IDs, section presence, support-need coverage, complaint account flag, “no summary on invalid path”.
2. **Judges**: LLM (CORTEX) scores claim-vs-context or rubric; fail = score below threshold + reason string on the dashboard.

**Compact example (TC_001 style):**  
Aggregate says Trusted Parties API failed → summary “No Trusted Party identified” → **missing_data_honesty** pass.  
If summary lists a fake trusted contact → fail (honesty + often faithfulness/hallucination too).

---

## Config map

| What | Where |
|------|--------|
| Gate judges | `configs/evaluations/fact_find_workflow/gate_validation.yaml` |
| Summary judges | `configs/evaluations/fact_find_workflow/summary_vs_aggregate.yaml` |
| GEval rubrics | `configs/criteria/fact_find_workflow/*.md` |
| CLI defaults (not package tests) | `configs/metrics/fact_find_workflow.yaml` |
| MCP catalog | `src/parsers/fact_find_workflow/mcp_catalog.py` |
