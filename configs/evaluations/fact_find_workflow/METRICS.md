# Fact Find metrics — why, what, how

Same layout as Knowledge Agent:

- **Catalog** = define metrics once (`configs/metrics/fact_find_workflow/catalog.yaml`)
- **Suites** = select judge names (`configs/evaluations/fact_find_workflow/*.yaml`)

Ground truth for the success path = aggregated payload
(`data/fact_find_workflow/aggregated_payloads/`), attached as `retrieval_context`
via `tests/fact_find_workflow/ff_eval.prepare_for_judges`.

---

## Suites

| Suite | When | Judges |
|-------|------|--------|
| **sanity** | Smoke / any case | `relevance` |
| **gate_validation** | `expected.path: invalid_complaint` | `validation_message_clarity`, `relevance` |
| **summary_vs_aggregate** | `expected.path: success` + aggregate | faithfulness, relevance, summarization, task_completion + 4 domain GEval |
| **e2e** | `include:` gate + summary | union of the above |

`RUN_JUDGES=true` on sanity tests picks **gate** or **summary** from `case.expected.path`.

---

## `gate_validation` — accept / reject the complaint ref

| Metric | Why | Catches |
|--------|-----|---------|
| **validation_message_clarity** (GEval) | Explain format (`NC` + 8 digits) | Vague InvalidComplaintId text |
| **relevance** | Reply about *this* input | Off-topic / wrong-path chatter |

---

## `summary_vs_aggregate` — UI summary vs aggregate

### Built-ins

| Metric | Why | How |
|--------|-----|-----|
| **faithfulness** | Anti-hallucination vs aggregate | Claims must be supported by `retrieval_context` |
| **relevance** | Summary answers the complaint-ref task | Input ref ↔ answer about that customer/case |
| **summarization** | UI is a *summary* of backend facts | Coverage vs `source_document` (aggregate) |
| **task_completion** | Usable FactFind delivered | Input → adequate summary |

### Domain GEval

| Metric | Why |
|--------|-----|
| **support_needs_fidelity** | Vulnerability data omit/rename is high severity |
| **profile_accuracy** | Identity must match OCIS/profile |
| **missing_data_honesty** | Failed APIs must not be papered over |
| **complaint_account_association** | Wrong account = wrong complaint context |

Deferred until tool traces are stable: `tool_correctness`, `mcp_use`, `mcp_task_completion`, `hallucination`, `contextual_relevancy` (defs can be added to the catalog later).

---

## Config map

| What | Where |
|------|--------|
| Metric definitions | `configs/metrics/fact_find_workflow/catalog.yaml` |
| Sanity / gate / summary / e2e suites | `configs/evaluations/fact_find_workflow/*.yaml` |
| GEval rubrics | `configs/criteria/fact_find_workflow/*.md` |
| Aggregate → context helper | `tests/fact_find_workflow/ff_eval.py` |
| MCP catalog | `src/parsers/fact_find_workflow/mcp_catalog.py` |
