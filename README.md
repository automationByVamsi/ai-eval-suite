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
make setup                                                       # installs everything, creates .env
make run AGENT=fact_find_workflow SUITE=sanity OFFLINE=1 JUDGES=0  # works right away, no network
```

That replays saved traces from `outputs/traces/` and runs the deterministic checks.
To call the real agent and the judges, fill in `.env` (see `.env.example`) and drop the flags:

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
| point an agent at a different URL / app / headers | `.env`, or `connection:` in `agents/<agent>/agent.yaml` |
| add or edit test cases                            | `agents/<agent>/testdata/<suite>/*.json` |
| add a suite (regression, goldens, …)              | `suites:` in `agents/<agent>/agent.yaml` + a `testdata/<suite>/` folder |
| choose which metrics a suite runs                 | `suites:` → `metrics: [...]` in `agents/<agent>/agent.yaml` |
| change a threshold                                | `metrics:` in `agents/<agent>/agent.yaml` |
| add / remove a **Pegasus** (or DeepEval) metric   | `metric_library.yaml` — then use it by name in any agent |
| add a custom judge for one agent                  | a rubric in `agents/<agent>/rubrics/` + one line under `metrics:` |
| judge a stage output (rewritten query, tool, …)   | expose it in `agents/<agent>/parser.py`, point the metric at it (`answer: rewritten_query`) |
| add a deterministic check for one agent           | `checks()` in `agents/<agent>/parser.py` |
| evaluate an agent that isn't Google ADK           | `agents/<agent>/client.py` (copy `client.py.example`) |
| judge model / CORTEX / Pegasus credentials        | `.env` |
| regression tolerance for verdicts                 | `PASS_RATE_DROP`, `SCORE_DROP` at the top of `evalkit/verdict.py` |

You should never need to edit `evalkit/` to onboard an agent or change metrics.

## Everyday commands

| I want to…                                  | Command |
|---------------------------------------------|---------|
| see agents, suites and their metrics        | `make list` |
| create a new agent                          | `make new-agent NAME=claims_agent INPUT_FIELD=claim_id` |
| run a suite                                 | `make run AGENT=fact_find_workflow SUITE=sanity` |
| rerun without calling the agent             | `... OFFLINE=1` |
| skip the LLM judges (fast, free)            | `... JUDGES=0` |
| run every case several times                | `... REPS=5` |
| save a stable build as the baseline         | `make baseline AGENT=.. SUITE=.. BUILD=1.4.0 REPS=5` |
| check a new build against the baseline      | `make verdict  AGENT=.. SUITE=.. BUILD=1.5.0 REPS=5` |
| look at results                             | `make dashboard` |
| test the framework itself                   | `make test` |

Every command exits with 1 when something failed, so it drops straight into CI.

## Project layout

```
metric_library.yaml             built-in metrics: Pegasus class, DeepEval fallback, fields they need
agents/
  <agent>/                      everything about one agent lives in its folder
    agent.yaml                  connection, metrics (+ thresholds), suites
    testdata/<suite>/*.json     test cases, one per file
    rubrics/*.md                custom judge criteria, in plain English     (optional)
    parser.py                   stage fields from the trace + own checks    (optional)
    client.py                   only for agents that are not Google ADK     (optional)
  _template/                    what `make new-agent` copies
evalkit/                        the framework (~1,100 lines) — start with runner.py
  runner.py                     steps 1–6
  judges.py                     how a metric is scored (engine rule, fields, skip/error)
  verdict.py                    baseline + verdict (step 7)
  adk.py                        Google ADK client + trace helpers for parsers
  cortex.py                     the judge LLM (CORTEX gateway) for DeepEval and Pegasus
  results.py, config.py, new_agent.py, __main__.py
baselines/<agent>/<suite>.json  committed, so the team compares against the same baseline
outputs/traces/                 latest trace per case (committed ones are offline fixtures)
outputs/runs/<run id>/          results.json + that run's traces (not committed)
dashboard.py  Makefile  tests/
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
`.env`, choose metrics and suites in `agent.yaml`, add test cases, `make run AGENT=claims_agent SUITE=sanity`.
Add `parser.py` logic only when you want stage fields or agent-specific checks —
`agents/knowledge_agent/parser.py` (40 lines) is a good example. For an agent that is not Google ADK,
rename `client.py.example` to `client.py` and fill in the three TODOs.

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
To reuse a run instead of running again: `uv run python -m evalkit verdict AGENT SUITE --from-run latest`.
A baseline is refused if its run had errors.

## Pass, fail, skip, error

| Status | Meaning | Effect on the case |
|---|---|---|
| pass  | check/judge passed | – |
| fail  | check failed, or judge score below threshold | case fails |
| skip  | the case doesn't have the data this judge needs | none |
| error | the agent or the judge couldn't run (network, auth, crash) | case errors |

An unreachable agent or judge is an **error** — never a pass, a skip, or a score of 0.

## Coming from the v1 framework (`main` before this branch)

| v1 | now |
|---|---|
| `configs/agents.yaml` | `connection:` + `input_field:` in `agents/<agent>/agent.yaml` |
| `configs/metrics/<agent>/catalog.yaml` | `metrics:` in `agents/<agent>/agent.yaml` |
| `configs/evaluations/<agent>/<suite>.yaml` | `suites:` in `agents/<agent>/agent.yaml` |
| `configs/criteria/<agent>/*.md` | `agents/<agent>/rubrics/*.md` |
| `configs/cortex.yaml` | `.env` |
| `testdata/<agent>/<suite>/` | `agents/<agent>/testdata/<suite>/` |
| `data/fact_find_workflow/aggregated_payloads/` | `agents/fact_find_workflow/ground_truth/` (case key: `expected.ground_truth`) |
| `make new-agent name=x` | `make new-agent NAME=x` |
| `make test-ka-sanity-judges` | `make run AGENT=knowledge_agent SUITE=sanity` |
| `EVAL_MODE=cache` / `RUN_JUDGES=false` | `OFFLINE=1` / `JUDGES=0` |
| `METRICS_SUITE`, `METRIC_MODE`, `sanity_pegasus` suites | not needed — the engine is chosen per metric |
| `make verdict-baseline` / `verdict-check` | `make baseline` / `make verdict` |

Rename these in your `.env` if you still have the old names:
`KNOWLEDGE_BASE_URL_LOCAL` → `KNOWLEDGE_ADK_BASE_URL`, `KNOWLEDGE_BASE_PATH_LOCAL` → `KNOWLEDGE_ADK_BASE_PATH`,
`KNOWLEDGE_APP_NAME_LOCAL` → `KNOWLEDGE_ADK_APP_NAME`, `KNOWLEDGE_USER_ID_LOCAL` → `KNOWLEDGE_ADK_USER_ID`,
`ADK_BASE_HOST` → `FACTFIND_ADK_BASE_URL`, `ADK_APP_NAME` → `FACTFIND_ADK_APP_NAME`, `ADK_USER_ID` → `FACTFIND_ADK_USER_ID`.
Only `.env` is read now (v1 also read `env/.env.factfind.api`) — copy the CORTEX values you need into `.env`.
Traces saved by v1 in `outputs/traces/` still replay with `OFFLINE=1`.

Not carried over (still in git history on `main`): the KA golden synthesizer, the Fact Find
ground-truth payload generator, the A/B comparison and Excel export branches.
