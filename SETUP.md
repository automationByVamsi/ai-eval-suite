# Setup

Set up the AI Eval Suite on your machine and run your first evaluation. Do the steps in order;
each one says **what to do**, **what you should see**, and **what to do if you don't**.

You need: a Mac or Linux machine, `git`, a terminal (the one in VS Code is fine), and network
access to the bank's services (VPN when remote). How the framework works: [README.md](README.md).

| Step | | Needs |
|---|---|---|
| 1 | [Install uv](#step-1--install-uv) | — |
| 2 | [Get the code](#step-2--get-the-code) | repository access |
| 3 | [Create your settings file](#step-3--create-your-settings-file) | — |
| 4 | [Fill in `env/.env`](#step-4--fill-in-envenv) | your credentials |
| 5 | [Install everything](#step-5--install-everything) | SAR token |
| 6 | [Sign in to CORTEX (DevKit only)](#step-6--sign-in-to-cortex-devkit-only) | DevKit access |
| 7 | [Check the machine](#step-7--check-the-machine) | — |
| 8 | [Check the framework](#step-8--check-the-framework) | — |
| 9 | [First run — offline](#step-9--first-run-offline) | nothing |
| 10 | [First run — live](#step-10--first-run-live) | agent URL, CORTEX, Athena |
| 11 | [Open the dashboard](#step-11--open-the-dashboard) | — |

Run every command from the repository folder (`ai-eval-suite`).

---

## Before you start: credentials to request

Ask for these first — they take the longest. They go **only** into `env/.env` on your machine
(Step 4), never into code, commits, chat or tickets.

| Credential | Used for | Without it |
|---|---|---|
| **SAR token** (token name + pass code — the one the Pegasus guide puts in `pip.conf`) | installing Pegasus and the CorteX DevKit | judges run on DeepEval instead of Pegasus; DevKit sign-in not possible |
| **CORTEX**: an API key (host, client id, key) **or** DevKit SSO access | the LLM judges | only `JUDGES=0` runs work |
| **Knowledge Agent** URL and ADK app name | calling the agent | only `OFFLINE=1` runs work |
| **Hive Athena MCP** client id + secret | page text for judges (faithfulness, hallucination, context recall/precision); the synthesizer | those judges ERROR |
| **Google Cloud** read access to the preprocessing buckets, and the `gcloud` CLI | `AGENT=knowledge_agent/ingestion` only (sign in with `make gcloud-auth`) | that agent's cases ERROR; nothing else is affected |

---

## Step 1 — Install uv

uv installs the right Python and every package for this project. You don't install Python yourself.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # or: brew install uv
```

Close and reopen the terminal, then:

```bash
uv --version      # 0.5 or newer
make --version    # any version
```

- `make: command not found` on a Mac → `xcode-select --install`, then reopen the terminal.
- `uv: command not found` → reopen the terminal (the installer adds uv to your PATH).

**Done when** both commands print a version.

---

## Step 2 — Get the code

```bash
git clone <repository URL> ai-eval-suite
cd ai-eval-suite
git checkout refactor-version-1
```

Open the folder in VS Code (`code .`) and use its terminal from now on.

**Done when** `git branch --show-current` prints `refactor-version-1`.

---

## Step 3 — Create your settings file

```bash
make setup
```

The first time, this copies `env/.env.example` to **`env/.env`** (your private settings file) and
installs what it can without credentials. You'll see `Created env/.env - fill in your values` and a
note that Pegasus is skipped — that's expected now.

**Done when** the file `env/.env` exists.

`env/` is git-ignored: `env/.env` is never committed. Check with `git status` — it must not list it.

---

## Step 4 — Fill in `env/.env`

Open `env/.env` in VS Code. Every setting is explained in the file; fill in these:

### Required

| Setting | Value |
|---|---|
| `SAR_TOKEN_NAME` | your SAR token name |
| `SAR_TOKEN_PASS_CODE` | your SAR token pass code |
| `VERIFY_TLS` | keep `false` (the office proxy re-signs HTTPS) — **or** delete it and set `CA_BUNDLE=/path/to/corporate-ca.pem` |
| `KNOWLEDGE_ADK_BASE_URL` | the Knowledge Agent URL, no trailing `/` |
| `KNOWLEDGE_ADK_APP_NAME` | the agent's ADK app name (usually `knowledge_agent`) |
| `HIVE_ATHENA_CLIENT_ID` | your Athena MCP client id |
| `HIVE_ATHENA_CLIENT_SECRET` | your Athena MCP client secret |
| `CORTEX_AUTH` | `api_key` or `devkit` — see below |
| `CORTEX_MODEL` | keep the value in the file unless told otherwise |

### CORTEX — fill one of the two

| If `CORTEX_AUTH=api_key` | If `CORTEX_AUTH=devkit` |
|---|---|
| `CORTEX_HOST` — the gateway URL, ending in `/v1` | `CORTEX_ENV` — `int`, `pre` or `prd` (optional; Pegasus defaults to `prd`) |
| `CORTEX_CLIENT_ID` | nothing else — you sign in with SSO in Step 6 |
| `CORTEX_API_KEY` | |

### Leave as they are (unless told otherwise)

`HIVE_ATHENA_BASE_URL` (already set to the test environment), `CORTEX_TIMEOUT_S`, `CORTEX_RETRIES`,
`KNOWLEDGE_ADK_BASE_PATH`, `KNOWLEDGE_ADK_USER_ID`, `CORTEX_BASE_URL`, `CORTEX_CLIENT_SECRET`,
`PEGASUS_CORTEX_MODEL`, `PEGASUS_CERT_PATH`.

### Format rules

- one `NAME=value` per line, no spaces around `=`, no quotes needed;
- comments go on their **own** line, never after a value;
- settings for one agent only can go in `env/.env.<agent>` (e.g. `env/.env.knowledge_agent`) —
  they override `env/.env` for that agent.

**Done when** every required setting has a value.

---

## Step 5 — Install everything

Now that `env/.env` has your SAR token:

```bash
make setup
```

Read the last lines:

| You see | Meaning / action |
|---|---|
| `Installed everything, including Pegasus and the CorteX DevKit.` | Done. |
| `… The CorteX DevKit could not be installed.` | Fine if you use `CORTEX_AUTH=api_key`; otherwise check the token and network, run again. |
| `… Pegasus could not be installed.` | Check the SAR token and that you're on the bank network/VPN, run again. |
| `NOTE: no SAR token in env/.env …` | `SAR_TOKEN_NAME` / `SAR_TOKEN_PASS_CODE` are empty or misspelt (Step 4). |

Always install with `make setup`, never a bare `uv sync` — `uv sync` doesn't know your token and
removes Pegasus.

**Done when** you see the first line of the table.

---

## Step 6 — Sign in to CORTEX (DevKit only)

Skip this step if `CORTEX_AUTH=api_key`.

```bash
make cortex-login
```

A browser opens for SSO; the token is stored in your keychain. Run it again whenever judges start
failing with an authentication error.

**Done when** the command finishes without an error.

---

## Step 7 — Check the machine

```bash
make doctor
```

One line per item, then one real call to CORTEX (and one Pegasus metric when Pegasus is installed).
Secrets are never printed.

| Line | Want | If not |
|---|---|---|
| `env files` | `[OK  ]` | you're not in the repository folder, or Step 3 wasn't done |
| `deepeval` | `[OK  ]` | `make setup` |
| `pegasus` | `[OK  ]` | `[WARN]` → Step 5 (judges still run, on DeepEval) |
| `certificates` | `[OK  ]` | `CA_BUNDLE` path doesn't exist → fix it, or use `VERIFY_TLS=false` |
| `CORTEX_AUTH` | `[OK  ]` | typo in `env/.env` |
| `CORTEX_HOST` or `CorteX DevKit` | `[OK  ]` | fill the CORTEX settings for your mode (Step 4) / Step 6 |
| `CORTEX call` | `[OK  ]` | see [Problems](#problems-during-setup) — the line names the URL it called |
| last line | `All good.` | fix each `[FAIL]` line and run `make doctor` again |

**Done when** the last line is `All good.`

---

## Step 8 — Check the framework

```bash
make test
```

The framework's own tests: offline, no credentials, ~10 seconds.

**Done when** it ends with `… passed` and no `failed`. A failure on a fresh checkout is a problem in
the code, not in your setup — report it.

---

## Step 9 — First run (offline)

Replays the traces saved in the repository (`outputs/traces/`) and runs the deterministic checks.
No agent, no CORTEX, no network.

```bash
make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1 JUDGES=0
```

You should see:

```
PASS  TC_002  [5 skipped]
PASS  TC_012  [5 skipped]
2 passed, 0 failed, 0 errors  ->  outputs/runs/<run id>/results.json
```

"skipped" means the sanity cases have no golden data for those checks (expected pages, source page),
or the check doesn't apply (the caveat check runs only for MEDIUM / LOW confidence) — not a failure.

**Done when** your output matches.

---

## Step 10 — First run (live)

Calls the agent and the judges. Run the three commands in order — each adds one service, so if one
fails you know which.

```bash
make run AGENT=knowledge_agent SUITE=sanity JUDGES=0          # 1. the agent only
make run AGENT=knowledge_agent SUITE=sanity                   # 2. + judges (CORTEX) and page text (Athena)
make fields AGENT=knowledge_agent CASE=TC_002                 # 3. what was read from the new trace
```

1. Both cases are evaluated with no `ERROR` (each question takes 10–60 s).
2. Each case also shows judge lines like `PASS  judge:relevance score=0.86/0.7 [pegasus]`.
   `judge:correctness` is SKIP — sanity cases have no golden answer.
3. Prints every field read from the trace (answer, anchor pages, …); none of the important ones
   should say `NOT FOUND`.

**Done when** all three work. `FAIL` lines are results about the agent, not setup problems;
`ERROR` lines are setup problems — see below.

---

## Step 11 — Open the dashboard

```bash
make dashboard
```

Opens http://localhost:8501. Choose the agent, suite and run in the left sidebar. Stop it with
`Ctrl+C` in the terminal.

**Done when** you can see your run from Step 10. You're set up — next, read
[README.md](README.md) for how the framework works and the everyday commands.

---

## Problems during setup

Start with `make doctor`: it checks most of these and prints the URL it called.

| You see | Fix |
|---|---|
| `make: *** No rule to make target …` | you're not in the repository folder — `cd ai-eval-suite` |
| `No module named '…'` (e.g. `jmespath`) | `git pull`, then `make setup`. Still there: `uv lock`, then `make setup` |
| `[WARN] pegasus … not installed` | SAR token in `env/.env`, bank network/VPN, `make setup` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | `VERIFY_TLS=false` in `env/.env`, or `CA_BUNDLE=<corporate CA file>` |
| CORTEX `401` / `403` | wrong or expired key (`CORTEX_API_KEY`, `CORTEX_CLIENT_ID`); with DevKit: `make cortex-login` |
| CORTEX `404` | wrong URL — compare the URL in the error with `CORTEX_HOST` (it must end in `/v1`) |
| CORTEX `429` | rate limited — it retries; run fewer cases (`CASE="TC_002"`) |
| case `ERROR`: connection refused / timed out | `KNOWLEDGE_ADK_BASE_URL` wrong, VPN off, or the agent environment is down |
| case `ERROR`: `get_page_content_from_athena(<id>) failed` | check `HIVE_ATHENA_CLIENT_ID` / `_SECRET` / `_BASE_URL` |
| `.git/index.lock` or `.git/HEAD.lock` exists | an earlier git command was interrupted: make sure none is running, delete the file |

More (results, trace format changes, imports): [README.md → Troubleshooting](README.md#troubleshooting).
