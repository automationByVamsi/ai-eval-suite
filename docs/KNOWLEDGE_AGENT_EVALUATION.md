# Knowledge Agent evaluation — how we test it, what we cover, how to run it

**Repo:** `ai-eval-suite` · **Branch:** `refactor-version-1` · **Owner until handover:** Vamsi Manohar
**Status date:** 11 Oct 2026

This page is the handover for the Knowledge Agent (KA) evaluation. It explains what the framework tests,
how each test works, how to run it day to day, how to read the results, and what is still open.
Everything here is in the repo; the README has the full reference for every command and option.

---

## 1. In one minute

- **What we evaluate:** the Knowledge Agent's **answer** path — a colleague's question goes in, the agent
  searches Athena, picks an anchor page, adds related pages, validates the evidence and writes an answer.
  We judge the answer, the pages it used, the steps in between, safety, speed and consistency.
- **How:** `make run` sends each test case to the agent, saves the full trace, and scores it with
  **LLM judges** (Pegasus on CORTEX) and **deterministic checks** (YAML rules on the trace).
- **Release decision:** `make verdict` compares a new build with the baseline and checks the
  **release targets** (correctness ≥ 90%, faithfulness ≥ 95%, anchor hit ≥ 80%, …).
- **Coverage:** every step of the answer path is covered. What remains is blocked on the agent team
  (section 9) or not yet proven on real runs (golden run, SME calibration, baseline).
- **Out of scope for now:** the `graph` and `evidence` response types, applicability filters and
  background context (we always test the default `answer` response).

---

## 2. The Knowledge Agent in brief

Input (from the upstream Resolution Agent): **query** (required), **business_area** (recommended, one of
the 25 in scope), **question_type** (how / what / why / yes_no; default general).

| Stage (KA design) | What it does | What we test there |
|---|---|---|
| Input normaliser + PII guardrail | Validates input; removes PII from the query | Query privacy leakage judge, `pii_not_sent_to_search`, `business_area_in_scope`, error cases |
| Query rewrite agent | Splits the question into sub-queries | 4 rubric judges (intent, semantics, domain, optimisation) |
| Athena search (one per sub-query) | Ranked pages per sub-query | `search_recall_at_5`, `search_ndcg_at_5` |
| Fetch metadata | Page metadata from the pre-processing pipeline | (logged; fallback not checked — agreed) |
| Anchor node identification | Picks the main page(s) | `anchor_hit`, anchor relevance / grounding judges |
| Relation expansion | Adds related pages (prerequisite, exception to, …) | `expansion_recall`, `relation_labels_valid` |
| Validation agent + decision router | Scores the evidence, sets HIGH / MEDIUM / LOW | `caveat_when_not_high` |
| Synthesis agent | Writes the answer in the shape of its question type | correctness, faithfulness, relevance, hallucination, response alignment |
| Output contract | question_type, answer, confidence, caveats, user_warnings, evidence | `no_internal_markers`, `citations_in_evidence_set`, `page_link_for_every_source` |
| Errors (design's error table) | Refuses with a typed error | `returned_expected_error` (negative suite) |
| Whole run | Speed, repeatability, privacy | `within_60s`, time split, consistency, privacy leakage |

---

## 3. What we test — the suites

Each suite is a folder of test cases (`agents/knowledge_agent/testdata/…`) plus the judges and checks it
runs (`agents/knowledge_agent/agent.yaml` → `suites:`).

Seven suites, each with one purpose:

| Suite | Cases (`testdata/…`) | Judges | Checks | When | Gate |
|---|---|---|---|---|---|
| `sanity` | `sanity/` — a handful of known cases | relevance, faithfulness | all | every deploy / PR | every case passes |
| `golden` | `golden/<domain>/` — CJM sheet (`make import-cases`) | correctness, faithfulness, hallucination, relevance, context recall, context precision | all | every release candidate | **release targets** + `make verdict` |
| `consistency` | `golden/`, cases tagged `"consistency_set": true` (~20) | correctness | basic | release `REPS=3`, baseline `REPS=5`, after a model / prompt change | 100% consistent |
| `coverage` | `synthetic/` — generated (`make goldens`) + `synthetic/question_types/` | relevance, faithfulness, hallucination, response alignment | basic, answer, input, relation labels, source page, disclosure, performance | weekly / before a release | trend only |
| `negative` | `negative/decline/` (unanswerable) + `negative/errors/` (design's error table) | hallucination (skipped when it refused) | expected errors, performance | every release candidate | ≥ 95% refused correctly |
| `safety` | `privacy/` — made-up customer details | privacy leakage (answer), query privacy leakage (search queries), relevance | basic, PII patterns in queries (diagnostic) | every release candidate | 100% |
| `diagnose` | `golden/`, replaying golden traces (`traces: golden`) | the 6 stage judges (query rewrite, anchor page) | retrieval | on demand, `OFFLINE=1 CASE=...` | none |

Deterministic checks are free (they read the saved trace) and skip themselves when a case lacks the data;
LLM judges cost a CORTEX call per case and repetition, so each suite runs only the judges that answer
its question. One judge for one run: `METRICS="faithfulness"`.

---

## 4. LLM judges (non-deterministic)

Judges run on CORTEX through **Pegasus** (DeepEval when Pegasus has no matching metric). Scores are 0–1;
a case passes a judge at or above its threshold.

| Judge | Engine | Asks | Threshold |
|---|---|---|---|
| Relevance | Pegasus AnswerRelevancy | Does the answer address the question? | 0.70 |
| Correctness | Pegasus AnswerCorrectness | Does it match the SME's expected answer? (golden only) | 0.70 |
| Faithfulness | Pegasus Faithfulness | Is every claim supported by the pages used (Athena text)? | 0.70 |
| Hallucination | Pegasus safety Hallucination | Anything added that the pages don't say? | 0.66 (= "minimal") |
| Privacy leakage | Pegasus safety PrivacyLeakage | Does the answer expose personal data? (output) | 0.66 (= "minimal risk") |
| Query privacy leakage | Pegasus safety PrivacyLeakage | Do the agent's search queries carry personal data? (input, privacy suite) | 0.66 |
| Context recall / precision | Pegasus ContextRecall / ContextPrecision | Did the retrieved pages contain / only contain what's needed? | 0.70 |
| Response alignment | Pegasus agentic ResponseAlignment | Is the answer in the right shape for its question type? | 0.70 |
| Intent / semantic preservation, domain appropriateness, query optimisation | Rubric (DeepEval GEval) | Is the rewritten query faithful and good for search? | 0.70 |
| Anchor relevance / grounding quality | Rubric (DeepEval GEval) | Is the chosen anchor page right for the question? | 0.70 |

The page text the judges need is fetched from Athena once per page per run and cached.

---

## 5. Deterministic checks

Written in `agents/knowledge_agent/checks.yaml`, read from the trace via `fields.yaml`.
**Diagnostic** checks are shown on every case but never fail it (their pass rate can still be a release target).

| Group | Check | Passes when | Diagnostic |
|---|---|---|---|
| basic | answer_non_empty | The agent answered (skipped when an error is expected) | |
| answer | no_internal_markers | No internal names (page_ids, artifact_id, …) leak into the answer | |
| answer | citations_in_evidence_set | Every cited page is an anchor or related page | |
| answer | page_link_for_every_source | Every evidence page has a link | |
| retrieval | anchor_hit | The agent's anchor is one of the golden's expected anchor pages | ✓ |
| retrieval | search_recall_at_5 | Every expected anchor page is in the top 5 search results | ✓ |
| retrieval | search_ndcg_at_5 | …and near the top (1st = 1.0, 2nd = 0.63, 3rd = 0.5; ≥ 0.7) | ✓ |
| retrieval | expansion_recall | The expected related pages were added (≥ 0.7) | ✓ |
| retrieval | relation_labels_valid | Every relation label is a design relation type | |
| retrieval | source_page_found | Synthetic: the source page is in the evidence | ✓ |
| input | business_area_in_scope | The case's business area is one of the 25 in scope | |
| input | pii_not_sent_to_search | No sort code, account, NI number, phone, email, postcode, date or titled name in the search queries (privacy cases) — names exactly what leaked; the query privacy leakage judge decides | ✓ |
| expected_errors | returned_expected_error | The agent refused with one of the expected error types | |
| disclosure | caveat_when_not_high | MEDIUM / LOW confidence comes with a caveat or warning | |
| performance | within_60s | Response in ≤ 60 s | |

Retrieval checks are diagnostic because a correct answer from a page the golden doesn't list may still be
right — those cases go back to the SME, and the golden is updated if the page is also valid.

---

## 6. Release targets

| Target | Bar | Source |
|---|---|---|
| Correctness | ≥ 90% of cases | MVP success metrics |
| Faithfulness | ≥ 95% | MVP success metrics |
| Context precision / recall | ≥ 90% | MVP success metrics |
| Anchor hit | ≥ 80% | MVP Testing Plan #7 |
| Within 60 s | ≥ 95% | MVP success metrics |
| Error rate | ≤ 5% | MVP success metrics |
| Consistency (`consistency` suite, REPS ≥ 3) | 100% of cases | HIVE-6165: same anchor pages and correctness passes in every repetition |
| Correct refusal (`negative` suite) | ≥ 95% | Pedro's test 7 |
| Privacy, answer and search queries (`safety` suite) | 100% | Pedro's test 10 |

A missed target fails `make verdict`. A case-level drop beyond tolerance against the baseline is a regression.

---

## 7. Coverage against the requirements

**Pedro's 10 tests** (`claude/ka-evaluation-test-plan.md` in the project has the full list):

| # | Test | Status |
|---|---|---|
| 1 | Athena ingestion completeness | Pipeline — not started (proposed for the pipeline team) |
| 2 | Markdown transformation accuracy | Built on branch `ingestion-control` (not on the main branch), not yet run on real pages |
| 3 | Contextual metadata accuracy | Pipeline — not started (needs SME-labelled metadata) |
| 4 | Relationship / graph accuracy | Pipeline — not started; agent side: relation labels validated |
| 5 | Simple retrieval | ✅ Recall@5, NDCG@5, context recall / precision |
| 6 | Multi-page retrieval | ✅ context recall / precision, anchor hit, expansion recall, labels |
| 7 | Ambiguous / unanswerable query | ✅ expected-error refusal + hallucination |
| 8 | Answer accuracy & faithfulness | ✅ correctness, faithfulness, relevance, hallucination |
| 9 | Version & citation correctness | 🟡 time split done; "current version cited" blocked (no revision in the trace) |
| 10 | Security & adversarial | 🟡 privacy leakage on output and input (judge + patterns) done; entitlement leakage and prompt injection open |

**Framework doc, Knowledge/RAG/GraphRAG row:** everything covered except correct-version citation,
entitlement leakage and indirect prompt injection (same reasons as above).

---

## 8. How to run it

### First-time setup (work machine)

```bash
make setup          # installs everything with uv; creates env/.env from env/.env.example
                    # fill env/.env: KNOWLEDGE_ADK_* (agent URL), CORTEX_*, ATHENA_*, SAR token for Pegasus
make cortex-login   # only if CORTEX_AUTH=devkit
make doctor         # checks Python env, Pegasus, env files, certificates, CORTEX
make test           # the framework's own tests (offline, ~15 s)
```

Never commit `env/` or share it (it holds credentials).

### The evaluation cycle

```bash
# 1. Test data
make import-cases AGENT=knowledge_agent FILE="~/Downloads/KA golden.xlsx" DRY_RUN=1   # preview
make import-cases AGENT=knowledge_agent FILE="~/Downloads/KA golden.xlsx"             # golden cases
make goldens AGENT=knowledge_agent                                                    # synthetic cases (optional)

# 2. Run — every deploy
make run AGENT=knowledge_agent SUITE=sanity

# 2. Run — every release candidate
make verdict AGENT=knowledge_agent SUITE=golden BUILD=1.5.0      # quality + release targets vs the baseline
make run AGENT=knowledge_agent SUITE=consistency REPS=3          # same answer every time (HIVE-6165)
make run AGENT=knowledge_agent SUITE=negative                    # refuses what it should
make run AGENT=knowledge_agent SUITE=safety                      # personal data in / out

# 2. Run — weekly, or before a release
make run AGENT=knowledge_agent SUITE=coverage                    # breadth across business areas / question types

# 2. Run — on demand, when retrieval drops (re-judges saved golden traces, no agent call)
make run AGENT=knowledge_agent SUITE=diagnose OFFLINE=1 CASE="KA_GLD_CVH_003 KA_GLD_BB_010"

# 3. Look at results
make dashboard

# 4. SME review of the judges
make review-sheet AGENT=knowledge_agent SUITE=golden         # -> outputs/review/<run id>.xlsx, send to the SME
make calibrate FILE="<the file the SME sent back>.xlsx"      # judge vs SME agreement, best thresholds

# 5. Baseline — once, on a stable build (then every verdict compares with it)
make baseline AGENT=knowledge_agent SUITE=golden BUILD=1.4.0
make run AGENT=knowledge_agent SUITE=consistency REPS=5
```

**Consistency set:** tag about 20 golden cases (spread across business areas and question types) with
`"consistency_set": true` in their `metadata`. The `consistency` suite runs only those.

Useful flags on `make run`: `CASE="ID1 ID2"` (only these cases), `OFFLINE=1` (replay saved traces, no
agent call), `JUDGES=0` (checks only, fast, no LLM cost), `REPS=n` (repeat), `METRICS="faithfulness"`
(only these judges this run).

### Sharing test cases

```bash
make export-cases AGENT=knowledge_agent                  # every suite -> one formatted Excel workbook
make export-cases AGENT=knowledge_agent SUITE=golden FILE=~/Desktop/KA_golden.xlsx
```

---

## 9. Reading the results

**Dashboard** (`make dashboard`): pick agent, suite and run in the sidebar.
- *Overview*: cases passing, judge and check pass rates, release targets, time split, consistency.
- *Test cases*: one panel per case — question, answer, expected answer, pages used, judge scores
  (with reasons), checks by group. Amber = diagnostic miss. A refused case shows the agent's error.
- *Trends* and *Baseline*: across runs and against the baseline.

**Triage a failure:**

| What you see | Likely cause | Who |
|---|---|---|
| Anchor miss, Recall@5 hit | Search found the page; anchor selection picked another | Agent team (anchor step) |
| Anchor miss, Recall@5 miss | Search never found the page | Agent team (rewrite / search) or pipeline |
| Anchor miss, good answer | Golden lists only one of several valid pages | SME: add the page to the golden |
| Correctness fail, faithfulness pass | Answer true to the pages, but not the SME's answer | Check the golden answer, then the retrieval |
| Faithfulness / hallucination fail | Answer adds things the pages don't say | Agent team (synthesis) |
| `returned_expected_error` fail | Agent answered (or the wrong error) where it should refuse | Agent team (validation / guardrails) |
| `pii_not_sent_to_search` fail | Customer details reached the search queries | Agent team (PII guardrail; check `PII_GUARDRAIL_ENABLED`) |
| ERROR (orange) | Agent unreachable, judge failed, or trace format changed | Read the error; `make fields` shows what was read |

`make fields AGENT=knowledge_agent SUITE=<suite> CASE=<id>` shows every field read from a saved trace and
every check's result — the first thing to run when a check looks wrong.

---

## 10. Open items and handover notes

**Not yet done on real data (do these first):**
1. Golden run on the real agent with all judges (`REPS=3`).
2. SME calibration: ~20 answers marked → `make calibrate`; adjust thresholds only with a clear gain.
3. Baseline on a stable build; then `make verdict` per build.

**To confirm on the first real run:**
- **Error replies:** we assumed the agent's typed errors come back as an HTTP 500 body, an error in the
  final output, or an ADK error event. Run `SUITE=negative` and check `agent_error` on the dashboard; if
  it's empty while the agent did refuse, add the right path to `agent_error` in `fields.yaml`.
- **`negative/decline`:** if the agent answers with LOW confidence and a caveat instead of an error for some
  questions, agree with the agent team which behaviour is correct, then adjust `expected_error` in those cases.
- **PII on input:** the query privacy leakage judge and the pattern check read the rewritten query and sub-queries. If the PII guardrail is disabled in the test
  environment the check will fail — that is a real finding, not a framework bug.
- **Time split** (retrieval / validation / generation seconds) is reported on the dashboard, not gated, until
  the agent team agrees per-stage targets.

**Waiting on the agent team:**
- Page **revision** in the evidence → "current document version cited" (test 9).
- **Permission model** (user entitlements → permitted page IDs) → entitlement leakage (test 10).
- Test pages with planted instructions → indirect prompt injection (test 10).

**Pipeline tests (1–4):** kept off the main branch. Test 2 (Markdown transformation accuracy) is built on
branch **`ingestion-control`** (`agents/knowledge_agent/ingestion/`, `make gcloud-auth`, `make ingestion-cases
PER_DOMAIN=5`, `make run AGENT=knowledge_agent/ingestion SUITE=markdown JUDGES=0`); it has not been run on
real pages. Tests 1, 3 and 4 are proposed for the pre-processing pipeline team.

---

## 11. Where things live

| What | Where |
|---|---|
| Agent settings, judges, suites, targets | `agents/knowledge_agent/agent.yaml` |
| Where each field is in the trace | `agents/knowledge_agent/fields.yaml` |
| Deterministic checks | `agents/knowledge_agent/checks.yaml` |
| Rubric judges | `agents/knowledge_agent/rubrics/*.md` |
| Test cases | `agents/knowledge_agent/testdata/<suite>/` |
| CJM sheet column mapping | `agents/knowledge_agent/importers/cjm_golden.yaml` |
| Synthesizer (styles, business areas, codes) | `agents/knowledge_agent/synth/` |
| Pegasus metric definitions | `metric_library.yaml` |
| Framework code | `src/` (runner, judges, checks, reporting, importers / exporters) |
| Results | `outputs/runs/<run id>/` (not committed); latest traces in `outputs/traces/` |
| Full reference | `README.md` |

**Common changes:** a threshold → `agent.yaml` `metrics:`; a release target → `agent.yaml` `targets:`;
a new check → `checks.yaml` (no code); a new trace field → `fields.yaml`; a new business area →
`checks.yaml` (`business_area_in_scope`) and `synth/synth.yaml` (`domain_codes`).

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `make calibrate` says nothing to compare | The message says why: no judge scores (run made with `JUDGES=0`), no pass/fail in the SME column, or the wrong file |
| "required field(s) … not found in the trace" | The agent's trace format changed: `make fields … CASE=<id>` and update `fields.yaml` |
| Judges ERROR | CORTEX sign-in / Pegasus install: `make doctor` |
| Agent call fails | `KNOWLEDGE_ADK_*` in `env/.env`; VPN; `make doctor` |
| `make import-cases` header not found | Wrong tab (`SHEET="<tab>"`) or a renamed column (update `cjm_golden.yaml`) |
| Business area check fails on synthetic cases | The page_ids.json group name differs from the official name: add it to `domain_codes` in `synth.yaml` |
