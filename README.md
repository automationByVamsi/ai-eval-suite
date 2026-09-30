# AI Eval Suite

One way to evaluate every AI agent:

1. call the agent with each test case
2. save the agent's trace
3. read the input and expected values from the test case
4. pull the relevant fields out of the trace
5. score them with deterministic checks and LLM judges (Pegasus first, DeepEval otherwise)
6. report pass / fail
7. save a stable build as a **baseline**, and give every new build a **verdict** against it

## Get started (5 minutes)

You need [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone <this repo> && cd ai-eval-suite
make setup                                                       # installs everything, creates env/.env
make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1 JUDGES=0 CASE="TC_001 TC_002"  # works right away, no network
```

That replays saved traces from `outputs/traces/` and runs the deterministic checks.
To call the real agent and the judges, fill in `env/.env` (see `env/.env.example`) and drop the flags:

```bash
make run AGENT=knowledge_agent SUITE=sanity
make dashboard
```

**Pegasus** is an internal package: install it into the environment (`uv pip install <pegasus package>`).
Without it, Pegasus metrics run on DeepEval, a warning is printed, and every result records
which engine scored it.

## Where do I change…?

| I want to…                                        | Change this |
|---------------------------------------------------|-------------|
| add a new agent                                   | `make new-agent NAME=my_agent INPUT_FIELD=question` |
| point an agent at a different URL / app / headers | `env/.env`, or `connection:` in `agents/<agent>/agent.yaml` |
| add or edit test cases                            | `agents/<agent>/testdata/<suite>/*.json` |
| add a suite (regression, goldens, …)              | `suites:` in `agents/<agent>/agent.yaml` + a `testdata/<suite>/` folder |
| choose which metrics a suite runs                 | `suites:` → `metrics: [...]` in `agents/<agent>/agent.yaml` |
| change a threshold                                | `metrics:` in `agents/<agent>/agent.yaml` |
| add / remove a **Pegasus** (or DeepEval) metric   | `metric_library.yaml` — then use it by name in any agent |
| add a custom judge for one agent                  | a rubric in `agents/<agent>/rubrics/` + one line under `metrics:` |
| judge a stage output (rewritten query, tool, …)   | expose it in `agents/<agent>/parser.py`, point the metric at it (`answer: rewritten_query`) |
| add a deterministic check for one agent           | `checks()` in `agents/<agent>/parser.py` |
| evaluate an agent that isn't Google ADK           | `agents/<agent>/client.py` (copy `client.py.example`) |
| generate test cases from documents (synthesizer)  | `agents/<agent>/synth/` — see [Synthesizer](#synthesizer-generate-test-cases) |
| judge model / CORTEX / Pegasus / Athena settings  | `env/.env` |
| regression tolerance for verdicts                 | `PASS_RATE_DROP`, `SCORE_DROP` at the top of `src/verdict/compare.py` |
| CORTEX timeout / retries / TLS / API key          | `CORTEX_TIMEOUT_S`, `CORTEX_RETRIES`, `CORTEX_VERIFY_TLS`, `CORTEX_API_KEY` in `env/.env` |
| an endpoint, header or auth scheme changed        | the matching file in `src/clients/` |
| add a new kind of synthesizer source (an API, …)  | one new file in `src/synthesizer/sources/` (copy `json_records.py`) |

You should never need to edit `src/` to onboard an agent or change metrics.

## Everyday commands

| I want to…                                  | Command |
|---------------------------------------------|---------|
| see agents, suites and their metrics        | `make list` |
| create a new agent                          | `make new-agent NAME=claims_agent INPUT_FIELD=claim_id` |
| run a suite                                 | `make run AGENT=knowledge_agent SUITE=sanity` |
| run only some cases                         | `... CASE="TC_001 TC_002"` |
| rerun without calling the agent             | `... OFFLINE=1` |
| skip the LLM judges (fast, free)            | `... JUDGES=0` |
| run every case several times                | `... REPS=5` |
| save a stable build as the baseline         | `make baseline AGENT=.. SUITE=.. BUILD=1.4.0 REPS=5` |
| check a new build against the baseline      | `make verdict  AGENT=.. SUITE=.. BUILD=1.5.0 REPS=5` |
| fetch source documents for the synthesizer  | `make sources AGENT=knowledge_agent [GROUP="…"] [IDS="36626"]` |
| generate test cases from them               | `make goldens AGENT=knowledge_agent [GROUP=…] [IDS=…]` |
| look at results                             | `make dashboard` |
| test the framework itself                   | `make test` |

Every command exits with 1 when something failed, so it drops straight into CI.

## Project layout

```
Makefile                        every command (make help)
metric_library.yaml             built-in metrics: Pegasus class, DeepEval fallback, fields they need
env/
  .env.example                  every setting, documented — `make setup` copies it to env/.env
  .env                          your values: CORTEX, Athena, agent URLs            (not committed)
  .env.<agent>                  optional, one agent's values; override env/.env    (not committed)
agents/
  <agent>/                      everything about one agent lives in its folder
    agent.yaml                  connection, metrics (+ thresholds), suites
    testdata/<suite>/*.json     test cases, one per file
    rubrics/*.md                custom judge criteria, in plain English     (optional)
    parser.py                   stage fields from the trace + own checks    (optional)
    client.py                   only for agents that are not Google ADK     (optional)
    synth/                      test-case generator: synth.yaml, styles/, instructions.md (optional)
  _template/                    what `make new-agent` copies
src/                            the framework — src/__init__.py has a map of it
  cli.py                        every make command lands here (python -m src ...)
  core/                         paths, env files, agent.yaml loading, result types, errors
  clients/                      adk_client (the agent), cortex_client (judge model), athena_client
  runners/                      suite_runner (steps 1-6 for every case), test_cases (loading test data)
  metrics/                      library (which metrics exist), judges (engine rule + DeepEval + Pegasus)
  verdict/                      baseline (save), compare (verdict + tolerances)
  reporting/                    console report, dashboard.py (Streamlit)
  synthesizer/                  generator, settings, documents, output_template,
                                sources/ (athena_mcp, files, json_records)
  onboarding/                   new_agent (make new-agent)
  utils/                        adk_trace (helpers for parser.py), text, html_text
tests/                          test_runner, test_metrics, test_verdict, test_synthesizer, test_clients
baselines/<agent>/<suite>.json  committed, so the team compares against the same baseline
outputs/traces/                 latest trace per case (committed ones are offline fixtures)
outputs/runs/<run id>/          results.json + that run's traces (not committed)
```

Every file starts with a comment saying what it does, who uses it and what you'd change there.
Reading order for the code: `src/runners/suite_runner.py` → `src/metrics/judges.py` →
`src/verdict/compare.py` → `src/clients/`.

**In a parser**, import the helpers from the framework:

```python
from src.core.results import check                                    # a deterministic check
from src.utils.adk_trace import state, find_event, event_json, tool_calls  # read the ADK trace
```

## A test case

```json
{
  "test_case_id": "TC_012",
  "description": "Third party reports a support need when the customer is not present",
  "input":    { "question": "A third party has called up and ..." },
  "expected": {
    "keywords": ["CARERS"],
    "expected_answer": "Always balance data privacy with ...",
    "expected_anchor_page_id": "8194"
  }
}
```

- `input.<input_field>` (from agent.yaml) is sent to the agent. Use `message_template:` in agent.yaml
  if the agent needs the input wrapped in a sentence.
- Everything in `expected` is optional. `keywords` are checked for every agent; anything else is
  used by that agent's `parser.py` checks or by judges.
- A judge that needs something the case doesn't have (e.g. `correctness` without `expected_answer`)
  is **skipped** for that case and shown as skipped.
- One file can also hold many cases: `{"cases": [ {...}, {...} ]}`.

## Metrics

**Built-in metrics** live in `metric_library.yaml`. Each entry says which Pegasus class and/or
DeepEval class implements it and which fields it needs:

```yaml
faithfulness:
  needs: [question, answer, contexts]
  pegasus: Faithfulness              # used when Pegasus is installed
  deepeval: FaithfulnessMetric       # used otherwise
```

To add a Pegasus metric, add an entry with its class name from `pegasus.metrics.rag`.
To remove one, delete the entry. Available today: relevance, faithfulness, correctness,
context_precision, context_recall (Pegasus + DeepEval), contextual_relevancy, summarization (DeepEval).

**An agent uses metrics by name** in its `agent.yaml`, with its own thresholds, and adds its own
rubric-based judges:

```yaml
metrics:
  relevance:   {threshold: 0.7}                    # from metric_library.yaml
  correctness: {threshold: 0.8}
  intent_preservation:                             # custom judge (DeepEval GEval)
    rubric: rubrics/intent_preservation.md
    answer: rewritten_query                        # judge the rewritten query, not the final answer

suites:
  sanity:     {metrics: [relevance]}                            # quick: one metric
  e2e:        {testdata: testdata/sanity, metrics: [relevance, correctness, intent_preservation]}
  regression: {metrics: [relevance, correctness]}               # data in testdata/regression/
```

**Which engine runs a metric — one rule:** a custom rubric runs on DeepEval GEval; a library metric
runs on **Pegasus if it has a `pegasus:` class and Pegasus is installed**, otherwise on DeepEval.
`engine: deepeval` on a metric forces DeepEval (rarely needed). `method: ragas` passes a Pegasus method.

**What a judge sees.** Judges read four standard fields:

| field             | default value |
|-------------------|---------------|
| `question`        | the case input sent to the agent |
| `answer`          | the agent's final answer |
| `contexts`        | the trace's `context` (retrieved documents), if any |
| `expected_answer` | the case's `expected.expected_answer` |

`parser.py` can override them or add more fields (e.g. `rewritten_query`, `anchor_page_content`), and
a metric can read a standard field from any of them (`answer: rewritten_query`). Custom rubrics
judge `question` + `answer` unless you list more: `needs: [question, answer, contexts]`.

## Add an agent

```bash
make new-agent NAME=claims_agent INPUT_FIELD=claim_id
```

This creates `agents/claims_agent/` from the template and prints the next steps: put its URL in
`env/.env`, choose metrics and suites in `agent.yaml`, add test cases, `make run AGENT=claims_agent SUITE=sanity`.
Add `parser.py` logic only when you want stage fields or agent-specific checks —
`agents/knowledge_agent/parser.py` (40 lines) is a good example. For an agent that is not Google ADK,
rename `client.py.example` to `client.py` and fill in the three TODOs.

## Synthesizer (generate test cases)

Generate many realistic test cases for any agent from source documents, with DeepEval's Synthesizer
(the generator model is the CORTEX model from `env/.env`). Three independent parts, all configured in the
agent's `synth/synth.yaml`:

```
SOURCE                        GENERATOR                          OUTPUT TEMPLATE
where documents come from  ─► styles × evolutions × quality  ─►  the JSON shape of this
(Athena, files, JSON, API)    filter; checks + de-duplication    agent's test cases
```

```
agents/knowledge_agent/synth/
  synth.yaml         source + styles + evolutions + quality filter + output template
  page_ids.json      page ids grouped by domain (used by the athena_mcp source)
  instructions.md    rules every generated question and answer must follow
  styles/*.md        one per question style: ## scenario / ## task / ## additional_guidance /
                     ## input_format / ## expected_output_format
  cache/             fetched documents (make sources); runs/  one manifest per generation run
```

```bash
make sources AGENT=knowledge_agent                                  # fetch every page in page_ids.json
make goldens AGENT=knowledge_agent GROUP="Recoveries Commercial Bank"  # generate for one domain
make goldens AGENT=knowledge_agent IDS="36626"                      # …or for specific pages
make run     AGENT=knowledge_agent SUITE=golden                     # evaluate the agent on them
```

**Sources.** Every source turns what it reads into the same document —
`{"id", "title", "text", "group", "metadata"}` — so the generator never knows where it came from.

| `source: {type: …}` | For | Settings |
|---|---|---|
| `athena_mcp` | knowledge-base pages from the Hive Athena MCP server | `ids_file`; `HIVE_ATHENA_*` in `env/.env` |
| `files` | a folder of `.txt` / `.md` / `.json` files; sub-folders become groups | `folder` (default `documents`) |
| `json_records` | one JSON file with a list of records (an API export, a table) | `file`, `records_key`, `id_field`, `group_field`, `title_field`, `text_fields` |
| your own | any other system | `src/synthesizer/sources/<name>.py` with `fetch(settings, ids, folder) -> [documents]` |

`ids_file` (any id-based source) groups ids: `[{"domain": "…", "page_ids": ["…"]}]` (`group`/`ids` also work).
`GROUP=` picks groups, `IDS=` picks ids. `make goldens` fetches whatever isn't in `cache/` yet;
`make sources` re-fetches on purpose.

**Generator.** One DeepEval Synthesizer run per document × style, so every case knows its exact source.
A document that fails doesn't stop the run. Cases with an empty or placeholder question/answer, and
duplicate questions, are dropped. Each run writes a manifest to `synth/runs/` (generated / skipped / failed).
Config mistakes stop the run before anything is generated: an unknown `## section` in a style,
evolution weights that don't add up to 1, a missing file.

**Output template.** `output:` in synth.yaml is the exact shape of one test case, with placeholders:
`{generated.input}` `{generated.expected_output}` `{source.id}` `{source.title}` `{source.metadata.<key>}`
`{style}` `{group}` `{group_slug}` `{run.id}` `{run.generated_at}` `{run.model}` `{agent.input_field}` `{id}` `{n:03}`.
Leave `output:` out to get the standard evaluation case (`input.<input_field>`, `expected.expected_answer`,
`metadata.approval_status: UNREVIEWED`). If a style asks for JSON in its `input_format`, the template can
read its fields: `{generated.input.request}` (cases where the JSON is missing that field are skipped).

- New cases are **added** next to existing ones (numbering continues). `REPLACE=1` clears the folders being
  generated into — only after generation succeeded.
- Generated cases start as `approval_status: UNREVIEWED`. They all run by default; a suite can keep only
  reviewed ones with `only: {metadata.approval_status: APPROVED}`.
- **Add a style:** a new `styles/<name>.md` + one line under `styles:`.
- **Another agent:** copy `agents/knowledge_agent/synth/`, change `source:` and `output:`.

## Baseline and verdict

```bash
make baseline AGENT=knowledge_agent SUITE=e2e BUILD=1.4.0 REPS=5    # on a build you trust
git add baselines/ && git commit -m "baseline knowledge_agent e2e @ 1.4.0"

make verdict  AGENT=knowledge_agent SUITE=e2e BUILD=1.5.0 REPS=5    # on the new build
```

LLM agents and judges aren't deterministic, so run each case several times (`REPS`). For every
case × check/judge the baseline stores the pass rate and mean score. The verdict **fails** when:

- a pass rate drops by 15 points or more (e.g. 100% → 80%), or
- a mean judge score drops by 0.10 or more — even if it is still above the threshold, or
- something in the baseline didn't run at all, or the run had agent/judge errors.

It also flags when a score came from a different engine than the baseline (not comparable).
To reuse a run instead of running again: `uv run python -m src verdict AGENT SUITE --from-run latest`.
A baseline is refused if its run had errors.

## Pass, fail, skip, error

| Status | Meaning | Effect on the case |
|---|---|---|
| pass  | check/judge passed | – |
| fail  | check failed, or judge score below threshold | case fails |
| skip  | the case doesn't have the data this judge needs | none |
| error | the agent or the judge couldn't run (network, auth, crash) | case errors |

An unreachable agent or judge is an **error** — never a pass, a skip, or a score of 0.

## Coming from the earlier `evalkit/` layout of this branch

Same behaviour, new places. `make` commands are unchanged; `python -m evalkit` is now `python -m src`.

| was | now |
|---|---|
| `evalkit/runner.py` | `src/runners/suite_runner.py` + `src/runners/test_cases.py` |
| `evalkit/judges.py` | `src/metrics/judges.py` + `src/metrics/library.py` |
| `evalkit/verdict.py` | `src/verdict/baseline.py` + `src/verdict/compare.py` (+ printing in `src/reporting/console.py`) |
| `evalkit/adk.py` | `src/clients/adk_client.py` + trace helpers in `src/utils/adk_trace.py` |
| `evalkit/cortex.py` | `src/clients/cortex_client.py` |
| `evalkit/config.py` | `src/core/agent_config.py`, `src/core/env.py`, `src/core/paths.py` |
| `evalkit/results.py` | `src/core/results.py` (+ `src/reporting/console.py`) |
| `evalkit/synth.py` | `src/synthesizer/` (generator, settings, documents, output_template) |
| `evalkit/sources/`, `sources/athena_mcp.py` | `src/synthesizer/sources/` (+ `src/clients/athena_client.py`) |
| `evalkit/new_agent.py` | `src/onboarding/new_agent.py` |
| `dashboard.py` | `src/reporting/dashboard.py` |
| `.env`, `.env.example` | `env/.env`, `env/.env.example` (a root `.env` is still read if `env/.env` is missing) |
| in parser.py: `from evalkit import adk, check` | `from src.core.results import check` and `from src.utils.adk_trace import state, ...` |

## Coming from the v1 framework (`main` before this branch)

| v1 | now |
|---|---|
| `configs/agents.yaml` | `connection:` + `input_field:` in `agents/<agent>/agent.yaml` |
| `configs/metrics/<agent>/catalog.yaml` | `metrics:` in `agents/<agent>/agent.yaml` |
| `configs/evaluations/<agent>/<suite>.yaml` | `suites:` in `agents/<agent>/agent.yaml` |
| `configs/criteria/<agent>/*.md` | `agents/<agent>/rubrics/*.md` |
| `configs/cortex.yaml` (timeout, retries, verify, auth header) | `CORTEX_TIMEOUT_S`, `CORTEX_RETRIES`, `CORTEX_VERIFY_TLS`, `CORTEX_API_KEY` in `env/.env` |
| `testdata/<agent>/<suite>/` | `agents/<agent>/testdata/<suite>/` |
| `make new-agent name=x` | `make new-agent NAME=x` |
| `make test-ka-sanity-judges` | `make run AGENT=knowledge_agent SUITE=sanity` |
| `EVAL_MODE=cache` / `RUN_JUDGES=false` | `OFFLINE=1` / `JUDGES=0` |
| `METRICS_SUITE`, `METRIC_MODE`, `sanity_pegasus` suites | not needed — the engine is chosen per metric |
| `make verdict-baseline` / `verdict-check` | `make baseline` / `make verdict` |
| `configs/synthesizers/knowledge_agent/*` (config, evolution, filtration yaml) | one `agents/knowledge_agent/synth/synth.yaml` + `instructions.md` + `styles/` |
| `data/knowledge_agent/source_docs/`, `configs/synthesizers/knowledge_agent/page_ids.json` | `agents/knowledge_agent/synth/cache/`, `…/synth/page_ids.json` |
| `src/clients/hive_athena_mcp_client.py` + `src/synthesizer/clean.py` | `src/clients/athena_client.py` + `src/synthesizer/sources/athena_mcp.py` |
| `make synth-ka-prepare` / `synth-ka-generate` | `make sources AGENT=knowledge_agent` / `make goldens AGENT=knowledge_agent` |
| `make synth-ka-generate-page PAGE_ID=…` / `-domain DOMAIN=…` | `make goldens AGENT=knowledge_agent IDS=…` / `GROUP=…` |
| synthesized cases' `reference.answer` | `expected.expected_answer` (set in the output template) |
| `testdata/knowledge_agent/golden/` | `agents/knowledge_agent/testdata/golden/` (suite `golden`, key `expected_answer`) |
| `HIVE_ATHENA_CLIENT_ID` / `HIVE_ATHENA_CLIENT_SECRET` (Athena MCP) | same names, in `env/.env`; the server URL is now `HIVE_ATHENA_BASE_URL` |

Rename these in your `env/.env` if you still have the old names:
`KNOWLEDGE_BASE_URL_LOCAL` → `KNOWLEDGE_ADK_BASE_URL`, `KNOWLEDGE_BASE_PATH_LOCAL` → `KNOWLEDGE_ADK_BASE_PATH`,
`KNOWLEDGE_APP_NAME_LOCAL` → `KNOWLEDGE_ADK_APP_NAME`, `KNOWLEDGE_USER_ID_LOCAL` → `KNOWLEDGE_ADK_USER_ID`.
Settings are read from `env/.env` (shared) and `env/.env.<agent>` (one agent, overrides the shared file); a root `.env` is still read when `env/.env` doesn't exist. `env/.env.factfind.api` is no longer read — copy the CORTEX values you need into `env/.env`.
Traces saved by v1 in `outputs/traces/` still replay with `OFFLINE=1`.

Not carried over (still in git history on `main`): the Fact Find Workflow agent (being decommissioned —
its agent folder, parser, rubrics, ground-truth payloads and payload generator), the A/B comparison and
Excel export branches. To bring an agent like it back later: `make new-agent`, then copy its rubrics and
parser logic from `main`.
