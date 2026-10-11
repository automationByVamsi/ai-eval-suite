# Migration notes

Where things moved, for anyone coming from an older layout of this repository.

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
| `configs/cortex.yaml` (timeout, retries, verify, auth header) | `CORTEX_TIMEOUT_S`, `CORTEX_RETRIES`, `CORTEX_API_KEY`, `VERIFY_TLS` in `env/.env` |
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
