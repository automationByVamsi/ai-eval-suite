# Knowledge Agent — QE Validation Strategy

> Based on `sample-response.json` — query: `braille support need`
> Session: `dd074f1d-67fe-4416-ace7-cfd4d8568c53` | Latency: `35463ms` | Events: 21

---

## 1. Purpose

Validate that the knowledge agent:

1. Accepts and preserves the user query
2. Rewrites the query correctly
3. Retrieves relevant search artifacts
4. Selects the correct anchor page
5. Expands the anchor using valid relationships
6. Builds sufficient validation context
7. Produces a grounded answer
8. Rejects poor answers through guardrails
9. Returns the correct final API structure

**Reference run:**

| Item | Value |
|---|---|
| Input query | `braille support need` |
| Anchor page | `8224 — Braille Support Need` |
| Related page | `8208 — Types of Accessible Format Statements for Customers with Vulnerabilities` |
| Relationship | `procedural_guidance` |
| Decision | `FINISH` |
| Confidence | `HIGH` |
| Guardrail faithfulness | `0.94` |
| Guardrail relevancy | `0.94` |

---

## 2. How to Read an ADK Event

Each raw event contains the following fields:

| Field | Meaning | Use for validation |
|---|---|---|
| `author` | Event owner (agent or workflow name) | Grouping only — not unique per node |
| `nodeInfo.path` | Full execution path | **Primary event identification** |
| `content.parts[].text` | LLM response text or operational log message | Inspect model decisions |
| `output` | Structured data passed to the next node | Validate inter-node data flow |
| `actions.stateDelta` | State written to session by this event | Validate persisted workflow state |
| `actions.route` | Workflow routing decision | Validate control flow |
| `nodeInfo.messageAsOutput` | LLM message is delegated as this node's output | Explains why LLM events have empty `stateDelta` |
| `id` | Unique event identifier | Traceability |
| `invocationId` | Groups all events from one execution | Correlation |

### Key rule: `author` vs `nodeInfo.path`

Multiple events share the same `author` because several nodes inside a named workflow all emit events under that workflow's name. Always use `nodeInfo.path` to identify the exact node.

**Example — three events all with `author: "anchor_node_workflow"`:**

| `nodeInfo.path` | What it actually is |
|---|---|
| `.../anchor_branch_node@1` | Branch result (single artifact) |
| `.../run_parallel_anchor_branches_node@1` | Parallel collector |
| `.../anchor_node_identification_node@1` | State persistence |

### Validation priority

```
1. actions.stateDelta  →  persisted workflow state
2. output              →  structured data passed to another node
3. content.parts.text  →  LLM response or operational log
```

LLM events (author = agent name, `modelVersion` present, `messageAsOutput: true`) always have `stateDelta: {}`. The following workflow node parses and persists the LLM result.

---

## 3. Event-by-Event Validation Reference

### Event 1 — `pii_input_guardrail`

**Node path:** `knowledge_agent_workflow@1/pii_input_guardrail@1`

**Purpose:** Handles the raw user input. Records that PII guardrail is disabled. Passes the original query forward.

**Key values:**

```json
"content.parts[0].text": "PII input guardrail is disabled"
"output.parts[0].text": "braille support need"
"stateDelta": {}
```

**Assertions:**

```python
assert event["output"]["parts"][0]["text"] == "braille support need"
assert event["actions"]["stateDelta"] == {}
```

---

### Event 2 — `init_context_node`

**Node path:** `knowledge_agent_workflow@1/init_context_node@1`

**Purpose:** Initialises all workflow state fields. Sets the query and business area. Creates empty collections for all downstream stages.

**Expected stateDelta:**

```json
{
  "query": "braille support need",
  "business_area": "/Customer_Vulnerability_Hub/",
  "short_answer": false,
  "rewritten_query": [],
  "artifact_id": [],
  "filtered_page_ids": [],
  "anchor_page_id": [],
  "rule_based_expansion": [],
  "expanded_page_ids": [],
  "retrieved_set": [[], []],
  "user_warnings": []
}
```

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["query"] == "braille support need"
assert state["business_area"] == "/Customer_Vulnerability_Hub/"
assert state["short_answer"] is False
assert state["rewritten_query"] == []
assert state["artifact_id"] == []
```

---

### Event 3 — `query_rewrite_agent` *(LLM)*

**Node path:** `knowledge_agent_workflow@1/search_engine_workflow@1/query_rewrite_agent@1`

**Purpose:** LLM rewrites the user query to improve search recall. Classifies the query as simple or complex.

**Model output (in `content.parts[0].text`):**

```json
{
  "query_type": "simple",
  "rewritten_query": ["braille support necessity"]
}
```

**Note:** `stateDelta` is empty — this is an LLM event with `messageAsOutput: true`.

**Assertions:**

```python
import json
result = json.loads(event["content"]["parts"][0]["text"])
assert result["query_type"] == "simple"
assert result["rewritten_query"] == ["braille support necessity"]
assert event["actions"]["stateDelta"] == {}
assert event["nodeInfo"]["messageAsOutput"] is True
```

---

### Event 4 — `validate_query_rewrite_node`

**Node path:** `knowledge_agent_workflow@1/search_engine_workflow@1/validate_query_rewrite_node@1`

**Purpose:** Parses and validates the LLM rewrite output. Persists the rewritten query into workflow state.

**Key stateDelta change:** `rewritten_query` populated from `[]` to `["braille support necessity"]`.

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["rewritten_query"] == ["braille support necessity"]
assert state["artifact_id"] == []
```

---

### Event 5 — `search_node`

**Node path:** `knowledge_agent_workflow@1/search_engine_workflow@1/search_node@1`

**Purpose:** Executes semantic search using the rewritten query. Stores the search artifact ID.

**Log message:**

```
Search retrieved successfully for all sub-queries.
result_count=5 deduplicated_page_ids=5
```

**Key stateDelta change:** `artifact_id` populated.

```json
"artifact_id": ["a4624dd6-83b6-4e9f-bd1d-e7c72b40c6db"]
```

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert len(state["artifact_id"]) == 1
assert state["artifact_id"][0] == "a4624dd6-83b6-4e9f-bd1d-e7c72b40c6db"
assert "result_count=5" in event["content"]["parts"][0]["text"]
```

---

### Event 6 — `anchor_page_classifier_agent` *(LLM)*

**Node path:** `knowledge_agent_workflow@1/anchor_node_workflow@1/run_parallel_anchor_branches_node@1/anchor_branch_node@1/anchor_page_classifier_agent@1`

**Purpose:** LLM compares filtered candidate pages and selects the best anchor page for the query.

**Model output (in `content.parts[0].text`):**

```json
{
  "anchor_page_id": "8224",
  "rationale": "Page 8224, 'Braille Support Need', directly addresses..."
}
```

**Note:** `stateDelta` is empty — LLM event. Selection is not yet persisted.

**Assertions:**

```python
result = json.loads(event["content"]["parts"][0]["text"])
assert result["anchor_page_id"] == "8224"
assert result["rationale"]
assert event["actions"]["stateDelta"] == {}
assert event["nodeInfo"]["messageAsOutput"] is True
```

---

### Event 7 — `anchor_branch_node`

**Node path:** `knowledge_agent_workflow@1/anchor_node_workflow@1/run_parallel_anchor_branches_node@1/anchor_branch_node@1`

**Purpose:** Combines metadata-filter results with the LLM anchor decision. Produces a structured result for the artifact branch.

**Output:**

```json
{
  "artifact_id": "a4624dd6-83b6-4e9f-bd1d-e7c72b40c6db",
  "filtered_page_ids": ["8224", "27393"],
  "anchor_page_id": "8224",
  "rationale": "..."
}
```

**Note:** `filtered_page_ids` contains all pages that passed metadata filtering (both `8224` and `27393`). Only `8224` was selected as anchor. `stateDelta` is still empty.

**Assertions:**

```python
output = event["output"]
assert output["anchor_page_id"] == "8224"
assert "8224" in output["filtered_page_ids"]
assert "27393" in output["filtered_page_ids"]
assert output["rationale"]
assert event["actions"]["stateDelta"] == {}
```

---

### Event 8 — `run_parallel_anchor_branches_node`

**Node path:** `knowledge_agent_workflow@1/anchor_node_workflow@1/run_parallel_anchor_branches_node@1`

**Purpose:** Runs one anchor branch per search artifact in parallel. Collects successful results into a list.

**Output shape:** Always a list — one item per artifact branch.

```json
[
  {
    "artifact_id": "a4624dd6-...",
    "filtered_page_ids": ["8224", "27393"],
    "anchor_page_id": "8224",
    "rationale": "..."
  }
]
```

**Note:** The parallel collector carries the branch results in `output`, but `anchor_page_id` and `filtered_page_ids` are still empty in `stateDelta`. Persistence happens in Event 9.

**Assertions:**

```python
results = event["output"]
assert isinstance(results, list)
assert len(results) == 1
assert results[0]["anchor_page_id"] == "8224"
assert event["actions"]["stateDelta"]["anchor_page_id"] == []
assert event["actions"]["stateDelta"]["filtered_page_ids"] == []
```

---

### Event 9 — `anchor_node_identification_node`

**Node path:** `knowledge_agent_workflow@1/anchor_node_workflow@1/anchor_node_identification_node@1`

**Purpose:** Reads the collected branch outputs and persists anchor data into workflow state.

**Key stateDelta changes:**

```json
{
  "filtered_page_ids": [["8224", "27393"]],
  "anchor_page_id": ["8224"]
}
```

**Nesting explained:**
- Outer list = one entry per artifact/branch
- Inner list = page IDs for that branch

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["filtered_page_ids"] == [["8224", "27393"]]
assert state["anchor_page_id"] == ["8224"]
assert state["anchor_page_id"][0] in state["filtered_page_ids"][0]
```

---

### Event 10 — `relation_expansion_classifier_agent` *(LLM)*

**Node path:** `knowledge_agent_workflow@1/relation_expansion_workflow@1/run_parallel_relation_branches_node@1/relation_branch_node@1/relation_expansion_classifier_agent@1`

**Purpose:** LLM evaluates the anchor page's dependency graph and selects related pages that add value for the query.

**Model output (in `content.parts[0].text`):**

```json
{
  "expanded_page_ids": ["8208"],
  "rationale": "The page provides details on various accessible formats..."
}
```

**Note:** `stateDelta` is empty — LLM event. Page `8208` was offered as an LLM candidate because it appeared in `page_8224_enriched_tagged.json` with `relationship_label: "procedural_guidance"`.

**Assertions:**

```python
result = json.loads(event["content"]["parts"][0]["text"])
assert result["expanded_page_ids"] == ["8208"]
assert result["rationale"]
assert event["actions"]["stateDelta"] == {}
```

---

### Event 11 — `relation_branch_node`

**Node path:** `knowledge_agent_workflow@1/relation_expansion_workflow@1/run_parallel_relation_branches_node@1/relation_branch_node@1`

**Purpose:** Packages the relation classifier result into a structured branch output.

**Output:**

```json
{
  "artifact_id": "a4624dd6-...",
  "anchor_page_id": "8224",
  "rule_based_expansion": [],
  "expanded_page_ids": ["8208"],
  "rationale": "..."
}
```

**Assertions:**

```python
output = event["output"]
assert output["anchor_page_id"] == "8224"
assert output["expanded_page_ids"] == ["8208"]
assert output["rule_based_expansion"] == []
assert event["actions"]["stateDelta"] == {}
```

---

### Event 12 — `run_parallel_relation_branches_node`

**Node path:** `knowledge_agent_workflow@1/relation_expansion_workflow@1/run_parallel_relation_branches_node@1`

**Purpose:** Collects relation branch results from all parallel branches into a list.

**Log message:**

```
Relation expansion completed successfully for all branches.
artifact_count=1 branch_count=1 success_count=1 failure_count=0
```

**Note:** `expanded_page_ids` is still empty in `stateDelta`. Persistence happens in Event 13.

**Assertions:**

```python
results = event["output"]
assert isinstance(results, list)
assert len(results) == 1
assert results[0]["expanded_page_ids"] == ["8208"]
assert event["actions"]["stateDelta"]["expanded_page_ids"] == []
```

---

### Event 13 — `relation_expansion_node`

**Node path:** `knowledge_agent_workflow@1/relation_expansion_workflow@1/relation_expansion_node@1`

**Purpose:** Validates the LLM-selected IDs against allowed candidates, attaches relationship labels, and persists into workflow state.

**Key stateDelta changes:**

```json
{
  "rule_based_expansion": [[]],
  "expanded_page_ids": [
    [
      ["8208", "procedural_guidance"]
    ]
  ]
}
```

**Nesting explained:**

```
expanded_page_ids
  [0]          → branch index (per artifact)
    [0]        → relationship entry index
      [0]      → page_id
      [1]      → relationship_label
```

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["expanded_page_ids"][0][0] == ["8208", "procedural_guidance"]
assert state["rule_based_expansion"] == [[]]
```

---

### Event 14 — `prepare_validation_input_node`

**Node path:** `knowledge_agent_workflow@1/validation_workflow@1/prepare_validation_input_node@1`

**Purpose:** Fetches full page content for the anchor and all related pages. Persists the retrieved page set. Produces page content for the validation LLM.

**Key stateDelta change — `retrieved_set` now populated:**

```json
{
  "retrieved_set": [
    [["8224", "a4624dd6-83b6-4e9f-bd1d-e7c72b40c6db"]],
    [["8208", "a4624dd6-83b6-4e9f-bd1d-e7c72b40c6db", "procedural_guidance"]]
  ]
}
```

**retrieved_set structure:**
- `retrieved_set[0]` = anchor pages: `[page_id, artifact_id]`
- `retrieved_set[1]` = relation pages: `[page_id, artifact_id, relationship_label]`

**Output contains full page text** for anchor (`8224`) and neighbor (`8208`).

**Assertions:**

```python
state = event["actions"]["stateDelta"]
output = event["output"]

assert state["retrieved_set"][0][0][0] == "8224"
assert state["retrieved_set"][1][0][0] == "8208"
assert state["retrieved_set"][1][0][2] == "procedural_guidance"

assert output["query"] == "braille support need"
assert output["anchor_page_content"]
assert output["neighbor_page_content"]
```

---

### Event 15 — `validation_agent` *(LLM)*

**Node path:** `knowledge_agent_workflow@1/validation_workflow@1/validation_agent@1`

**Purpose:** LLM evaluates whether the retrieved context is applicable to the business area, relevant to the query, and sufficient to answer it.

**Model output (in `content.parts[0].text`):**

```json
{
  "context_applicability": 1.0,
  "context_relevance": 1.0,
  "context_sufficiency": 1.0,
  "applicability_reason": "...",
  "relevance_reason": "...",
  "sufficiency_reason": "..."
}
```

**Note:** `stateDelta` is empty — LLM event.

**Assertions:**

```python
result = json.loads(event["content"]["parts"][0]["text"])
assert result["context_applicability"] == 1.0
assert result["context_relevance"] == 1.0
assert result["context_sufficiency"] == 1.0
assert result["applicability_reason"]
assert result["relevance_reason"]
assert result["sufficiency_reason"]
assert event["actions"]["stateDelta"] == {}
```

---

### Event 16 — `validation_action_router_node`

**Node path:** `knowledge_agent_workflow@1/validation_action_router_node@1`

**Purpose:** Parses the validation LLM result. Decides whether to finish, retry, or loop back for more context. Persists the full validation result and routes the workflow.

**Key stateDelta additions:**

```json
{
  "context_relevance": 1.0,
  "context_applicability": 1.0,
  "context_sufficiency": 1.0,
  "decision": "FINISH",
  "confidence": "HIGH"
}
```

**Route:**

```json
"route": "FINISH"
```

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["decision"] == "FINISH"
assert state["confidence"] == "HIGH"
assert event["actions"]["route"] == "FINISH"
assert state["context_relevance"] == 1.0
assert state["context_applicability"] == 1.0
assert state["context_sufficiency"] == 1.0
```

---

### Event 17 — `prepare_synthesizer_input_node`

**Node path:** `knowledge_agent_workflow@1/prepare_synthesizer_input_node@1`

**Purpose:** Formats the validated context and confidence into a structured prompt input for the synthesizer LLM.

**Output (not persisted to state):**

```json
{
  "query": "braille support need",
  "confidence": "HIGH",
  "anchor_page_content": "anchor_page:\npage_id: 8224\ntitle: Braille Support Need\ncontent: ...",
  "relation_sections_text": "relation_type: procedural_guidance\n- page_id: 8208\n..."
}
```

**Assertions:**

```python
output = event["output"]
assert output["query"] == "braille support need"
assert output["confidence"] == "HIGH"
assert "page_id: 8224" in output["anchor_page_content"]
assert "page_id: 8208" in output["relation_sections_text"]
assert event["actions"]["stateDelta"] == {}
```

---

### Event 18 — `agent_synthesizer_agent` *(LLM)*

**Node path:** `knowledge_agent_workflow@1/synthesizer_dispatch_node@1/agent_synthesizer_agent@1`

**Purpose:** LLM generates the final natural-language answer grounded in the anchor and relation page content.

**Model output (in `content.parts[0].text`):**

```json
{
  "answer": "The Braille Support Need is designed for...",
  "caveats": [],
  "output_type": "agent",
  "recommended_actions": []
}
```

**Note:** `stateDelta` is empty — LLM event with `messageAsOutput: true`.

**Assertions:**

```python
result = json.loads(event["content"]["parts"][0]["text"])
assert result["output_type"] == "agent"
assert result["answer"]
assert result["caveats"] == []
assert result["recommended_actions"] == []
assert event["actions"]["stateDelta"] == {}
```

---

### Event 19 — `synthesizer_dispatch_node`

**Node path:** `knowledge_agent_workflow@1/synthesizer_dispatch_node@1`

**Purpose:** Parses the synthesizer LLM response and exposes it as structured workflow output for the guardrail stage.

**Output:**

```json
{
  "result": {
    "output_type": "agent",
    "answer": "...",
    "recommended_actions": [],
    "caveats": []
  }
}
```

**Assertions:**

```python
result = event["output"]["result"]
assert result["output_type"] == "agent"
assert result["answer"]
assert isinstance(result["caveats"], list)
assert isinstance(result["recommended_actions"], list)
```

---

### Event 20 — `output_guardrail_node`

**Node path:** `knowledge_agent_workflow@1/output_guardrail_node@1`

**Purpose:** Measures faithfulness (answer grounded in context) and relevancy (answer matches query). Approves or rejects the response.

**Key stateDelta additions:**

```json
{
  "output_guardrail_faithfulness_score": 0.94,
  "output_guardrail_relevancy_score": 0.94,
  "output_guardrail_decision": true
}
```

**Assertions:**

```python
state = event["actions"]["stateDelta"]
assert state["output_guardrail_decision"] is True
assert state["output_guardrail_faithfulness_score"] >= 0.90
assert state["output_guardrail_relevancy_score"] >= 0.90
assert state["user_warnings"] == []
```

---

### Event 21 — `format_answer_node`

**Node path:** `knowledge_agent_workflow@1/format_answer_node@1`

**Purpose:** Assembles the final API response combining decision, confidence, answer, caveats, and recommended actions.

**Final output:**

```json
{
  "decision": "FINISH",
  "confidence": "HIGH",
  "output_type": "agent",
  "answer": "...",
  "recommended_actions": [],
  "caveats": []
}
```

**Note:** `stateDelta` is empty — this node formats and returns; it does not mutate state.

**Assertions:**

```python
output = event["output"]
assert output["decision"] == "FINISH"
assert output["confidence"] == "HIGH"
assert output["output_type"] == "agent"
assert output["answer"]
assert output["caveats"] == []
assert output["recommended_actions"] == []
```

---

## 4. State Progression Summary

| After event | New state fields added |
|---|---|
| Event 2 (`init_context_node`) | `query`, `business_area`, `short_answer`, all empty collections |
| Event 4 (`validate_query_rewrite_node`) | `rewritten_query: ["braille support necessity"]` |
| Event 5 (`search_node`) | `artifact_id: ["a4624dd6-..."]` |
| Event 9 (`anchor_node_identification_node`) | `filtered_page_ids: [["8224","27393"]]`, `anchor_page_id: ["8224"]` |
| Event 13 (`relation_expansion_node`) | `rule_based_expansion: [[]]`, `expanded_page_ids: [[["8208","procedural_guidance"]]]` |
| Event 14 (`prepare_validation_input_node`) | `retrieved_set` fully populated with `8224` and `8208` |
| Event 16 (`validation_action_router_node`) | `context_relevance`, `context_applicability`, `context_sufficiency`, `decision: "FINISH"`, `confidence: "HIGH"` |
| Event 20 (`output_guardrail_node`) | `output_guardrail_faithfulness_score: 0.94`, `output_guardrail_relevancy_score: 0.94`, `output_guardrail_decision: true` |

---

## 5. Page Relationship Context

The anchor page `8224` has two hyperlinks to page `8208` in its content. Both were classified with `relationship_label: "procedural_guidance"` during the enrichment pipeline. This is what made `8208` an LLM candidate during relation expansion.

**Verify from `page_8224_enriched_tagged.json`:**

```python
page = load_json("page_8224_enriched_tagged.json")

assert page["original_data"]["pageid"] == "8224"

deps = page["original_data"]["dependencies"]
assert len(deps) == 2
assert all(d["target_pageid"] == "8208" for d in deps)

rels = page["metadata"]["relationship_metadata"]
assert all(r["relationship_label"] == "procedural_guidance" for r in rels)
```

---

## 6. End-to-End Acceptance Criteria

A successful invocation must satisfy all of the following:

```python
# Input
assert raw_events[0]["output"]["parts"][0]["text"] == "braille support need"

# Query rewrite
state_after_rewrite = find_event("validate_query_rewrite_node")["actions"]["stateDelta"]
assert state_after_rewrite["rewritten_query"] == ["braille support necessity"]

# Search
state_after_search = find_event("search_node")["actions"]["stateDelta"]
assert len(state_after_search["artifact_id"]) == 1

# Anchor
state_after_anchor = find_event("anchor_node_identification_node")["actions"]["stateDelta"]
assert state_after_anchor["anchor_page_id"] == ["8224"]
assert "8224" in state_after_anchor["filtered_page_ids"][0]

# Relation expansion
state_after_relation = find_event("relation_expansion_node")["actions"]["stateDelta"]
assert state_after_relation["expanded_page_ids"][0][0] == ["8208", "procedural_guidance"]

# Retrieved set
state_after_prep = find_event("prepare_validation_input_node")["actions"]["stateDelta"]
assert state_after_prep["retrieved_set"][0][0][0] == "8224"
assert state_after_prep["retrieved_set"][1][0][0] == "8208"

# Validation
state_after_router = find_event("validation_action_router_node")["actions"]["stateDelta"]
assert state_after_router["context_relevance"] == 1.0
assert state_after_router["context_applicability"] == 1.0
assert state_after_router["context_sufficiency"] == 1.0
assert state_after_router["decision"] == "FINISH"
assert state_after_router["confidence"] == "HIGH"
assert state_after_router["route"] == "FINISH"  # check in actions directly

# Guardrail
state_after_guardrail = find_event("output_guardrail_node")["actions"]["stateDelta"]
assert state_after_guardrail["output_guardrail_decision"] is True
assert state_after_guardrail["output_guardrail_faithfulness_score"] >= 0.90
assert state_after_guardrail["output_guardrail_relevancy_score"] >= 0.90

# Final output
final_output = find_event("format_answer_node")["output"]
assert final_output["decision"] == "FINISH"
assert final_output["confidence"] == "HIGH"
assert final_output["output_type"] == "agent"
assert final_output["answer"]
assert final_output["caveats"] == []
assert final_output["recommended_actions"] == []
```

---

## 7. Test Categories

### 7.1 Functional (Happy Path)

| Test | Node to validate | Assertion |
|---|---|---|
| Query is preserved | `pii_input_guardrail` | `output.parts[0].text == input_query` |
| Query is rewritten | `validate_query_rewrite_node` | `stateDelta.rewritten_query` non-empty |
| Search artifact created | `search_node` | `stateDelta.artifact_id` length >= 1 |
| Anchor page selected | `anchor_node_identification_node` | `stateDelta.anchor_page_id == ["8224"]` |
| Relation page selected | `relation_expansion_node` | `expanded_page_ids[0][0][0] == "8208"` |
| Relationship label correct | `relation_expansion_node` | `expanded_page_ids[0][0][1] == "procedural_guidance"` |
| Retrieved set populated | `prepare_validation_input_node` | Both `8224` and `8208` in `retrieved_set` |
| Validation passes | `validation_action_router_node` | `decision == "FINISH"`, `confidence == "HIGH"` |
| Guardrail approves | `output_guardrail_node` | `output_guardrail_decision == True` |
| Final response correct | `format_answer_node` | `output_type`, `decision`, `confidence`, `answer` all present |

### 7.2 Negative Cases

| Scenario | Expected behaviour |
|---|---|
| No search results | `search_node` fails; no artifact in state |
| All anchor branches fail | `run_parallel_anchor_branches_node` raises; `user_warnings` populated |
| LLM selects page ID not in candidate list | `relation_expansion_node` rejects it; `expanded_page_ids` stays empty |
| Anchor page has no dependencies | Relation expansion returns empty; only anchor in `retrieved_set` |
| Validation scores below threshold | `decision != "FINISH"`; workflow loops or degrades |
| Synthesizer returns malformed JSON | `synthesizer_dispatch_node` fails to parse |
| Guardrail rejects the answer | `output_guardrail_decision == False`; answer not returned |
| Multiple accessible formats requested | Answer should recommend `Correspondence - Bespoke` |

### 7.3 Structural Tests

| Check | Where |
|---|---|
| All 21 expected events are present | `len(raw_events) == 21` |
| LLM events have empty `stateDelta` | Events 3, 6, 10, 15, 18 |
| Parallel collector outputs are lists | Events 8, 12 |
| `route` is only set on `validation_action_router_node` | Event 16 |
| `messageAsOutput: true` only on LLM agent events | Events 3, 6, 10, 15, 18 |
| State fields do not regress to empty after being set | Compare `stateDelta` across all events |

### 7.4 Answer Grounding Tests

Verify the final answer is supported by pages `8224` and `8208`. Required factual assertions:

| Fact | Source page |
|---|---|
| Braille support is for statements and letters | 8224 |
| Only one accessible correspondence support need at a time | 8224 |
| Multiple formats → use Correspondence – Bespoke | 8224 |
| Uses Contracted (Grade 2) Braille | 8208 |
| 1 print page = ~4 Braille pages | 8208 |
| Braille not available on plastic cards | 8208 |
| Debit card: 3 raised dots | 8208 |
| Credit card: curved notch | 8208 |
| PSNs are sent; PINs are not | 8208 |
| Up to 7 working days to appear on account | 8208 |
| Statements arrive 7–9 working days after statement date | 8208 |
| Produced by RNIB Services | 8208 |
| Sent via Royal Mail Articles for the Blind | 8208 |

---

## 8. ADK Event Patterns — Quick Reference

```
author = workflow or agent that owns the event
nodeInfo.path = exact node that executed (always use this for identification)

LLM event markers:
  - modelVersion is present
  - content.role == "model"
  - stateDelta == {}
  - messageAsOutput == true

Workflow node event markers:
  - stateDelta is non-empty (when state is being written)
  - output is structured data (not LLM text)
  - No modelVersion field

Parallel branch pattern:
  - Branch node        → output: { ... }          stateDelta: {}
  - Parallel collector → output: [{ ... }]        stateDelta: {} (or carries forward)
  - Persistence node   → output: absent/null      stateDelta: { field: [value] }

State nesting convention:
  filtered_page_ids   = [[branch_0_pages], [branch_1_pages], ...]
  anchor_page_id      = [branch_0_anchor, branch_1_anchor, ...]
  expanded_page_ids   = [[[page_id, label], ...], ...]
  retrieved_set[0]    = [[page_id, artifact_id], ...]            anchor pages
  retrieved_set[1]    = [[page_id, artifact_id, label], ...]     relation pages
```

---

## 9. Full Execution Flow

```
User input
  ↓
pii_input_guardrail          (Event 1)  — pass query through
init_context_node             (Event 2)  — initialise state
  ↓
query_rewrite_agent           (Event 3)  — LLM rewrites query
validate_query_rewrite_node   (Event 4)  — persist rewritten query
search_node                   (Event 5)  — search and persist artifact
  ↓
anchor_page_classifier_agent  (Event 6)  — LLM selects anchor
anchor_branch_node            (Event 7)  — package branch result
run_parallel_anchor_branches_node (Event 8)  — collect branches
anchor_node_identification_node   (Event 9)  — persist anchor to state
  ↓
relation_expansion_classifier_agent (Event 10) — LLM selects related pages
relation_branch_node              (Event 11) — package relation branch
run_parallel_relation_branches_node (Event 12) — collect branches
relation_expansion_node           (Event 13) — persist expanded pages + labels
  ↓
prepare_validation_input_node     (Event 14) — build context + persist retrieved_set
validation_agent                  (Event 15) — LLM scores context
validation_action_router_node     (Event 16) — persist scores + route to FINISH
  ↓
prepare_synthesizer_input_node    (Event 17) — format prompt
agent_synthesizer_agent           (Event 18) — LLM generates answer
synthesizer_dispatch_node         (Event 19) — package answer as structured output
  ↓
output_guardrail_node             (Event 20) — persist guardrail scores
format_answer_node                (Event 21) — return final API response
```
