# AI Eval Suite — Setup Guide

Installs the framework and verifies it with an offline and a live run. Follow the steps in order.
For how the framework works, see [README.md](README.md).

---

## 1. Requirements

### Platforms

| Platform | Support | Shell to use |
|---|---|---|
| macOS | Supported | Terminal or the VS Code terminal |
| Linux | Supported | Any terminal |
| Windows 10 / 11 — **WSL 2** | Recommended for Windows | Ubuntu (WSL) terminal |
| Windows 10 / 11 — **Git Bash** | Alternative | Git Bash |

> **Windows:** not yet verified by the team. Use WSL 2 where possible: it behaves exactly like Linux.
> PowerShell and Command Prompt are not supported (the `make` commands need a Unix shell).

### Software

| Tool | Purpose |
|---|---|
| `git` | Get the code |
| `uv` 0.5+ | Installs Python and every package (do not install Python yourself) |
| `make` | Runs the commands in this guide |
| VS Code (optional) | Editor and terminal |

### Access and credentials

| Item | Used for | Without it |
|---|---|---|
| Repository access | Getting the code | — |
| Bank network / VPN | Every live call | Offline runs only |
| SAR token (token name + pass code) | Installing Pegasus and the CorteX DevKit | Judges run on DeepEval; no DevKit sign-in |
| CORTEX API key (host, client id, key) **or** DevKit SSO access | LLM judges | `JUDGES=0` runs only |
| Knowledge Agent URL + ADK app name | Calling the agent | `OFFLINE=1` runs only |
| Hive Athena MCP client id + secret | Page text for judges; the synthesizer | Faithfulness, hallucination and context judges ERROR |

> **Security:** credentials go only in `env/.env` on your machine. Never put them in code, commits,
> chat or tickets. `env/` is git-ignored.

---

## 2. Install the tools

Do **one** of the sections below, then check the result.

### macOS

```bash
xcode-select --install                                   # git and make (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh          # or: brew install uv
```

### Linux (Ubuntu / Debian)

```bash
sudo apt update && sudo apt install -y git make curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows — WSL 2 (recommended)

1. In **PowerShell as Administrator**:

   ```powershell
   wsl --install -d Ubuntu
   ```

2. Restart Windows. Open **Ubuntu** from the Start menu and create your Linux user.
3. In the Ubuntu terminal, follow the **Linux** section above.
4. Keep the repository inside the Linux file system (e.g. `~/ai-eval-suite`), not under `/mnt/c/`.
   It is much faster.
5. VS Code: install the **WSL** extension, then run `code .` from the Ubuntu terminal.

### Windows — Git Bash (alternative)

1. In **PowerShell**:

   ```powershell
   winget install --id Git.Git -e
   winget install --id astral-sh.uv -e
   winget install --id ezwinports.make -e
   ```

2. Open **Git Bash** and use it for every command in this guide.
3. Stop git from converting line endings (otherwise `make setup` fails):

   ```bash
   git config --global core.autocrlf input
   ```

### Check

Close and reopen the terminal, then:

```bash
git --version
uv --version        # 0.5 or newer
make --version
```

**Expected:** all three print a version.

---

## 3. Get the code

```bash
git clone <repository URL> ai-eval-suite
cd ai-eval-suite
git checkout refactor-version-1
```

**Expected:** `git branch --show-current` prints `refactor-version-1`.

Run every remaining command from the `ai-eval-suite` folder.

---

## 4. Create the settings file

```bash
make setup
```

**Expected:** `Created env/.env - fill in your values`, followed by a note that Pegasus is skipped.
`git status` must **not** list `env/.env`.

---

## 5. Fill in `env/.env`

Open `env/.env` in your editor. Format: one `NAME=value` per line, no spaces around `=`, no quotes,
comments on their own line.

### Required

| Setting | Value |
|---|---|
| `SAR_TOKEN_NAME` | SAR token name |
| `SAR_TOKEN_PASS_CODE` | SAR token pass code |
| `VERIFY_TLS` | `false` — or remove it and set `CA_BUNDLE=<path to corporate CA .pem>` |
| `KNOWLEDGE_ADK_BASE_URL` | Knowledge Agent URL, no trailing `/` |
| `KNOWLEDGE_ADK_APP_NAME` | ADK app name (usually `knowledge_agent`) |
| `HIVE_ATHENA_CLIENT_ID` | Athena MCP client id |
| `HIVE_ATHENA_CLIENT_SECRET` | Athena MCP client secret |
| `CORTEX_AUTH` | `api_key` or `devkit` |
| `CORTEX_MODEL` | Keep the value in the file |

### CORTEX — complete one column

| `CORTEX_AUTH=api_key` | `CORTEX_AUTH=devkit` |
|---|---|
| `CORTEX_HOST` — gateway URL ending in `/v1` | `CORTEX_ENV` — `int`, `pre` or `prd` (optional, default `prd`) |
| `CORTEX_CLIENT_ID` | Sign in at step 7 |
| `CORTEX_API_KEY` | |

All other settings: leave as they are. Settings for one agent only can go in
`env/.env.<agent>` (e.g. `env/.env.knowledge_agent`); they override `env/.env` for that agent.

**Expected:** every required setting has a value.

---

## 6. Install the packages

```bash
make setup
```

| Last line | Action |
|---|---|
| `Installed everything, including Pegasus and the CorteX DevKit.` | None — continue |
| `… The CorteX DevKit could not be installed.` | None if `CORTEX_AUTH=api_key`; otherwise check the SAR token and VPN, run again |
| `… Pegasus could not be installed.` | Check the SAR token and VPN, run again |
| `NOTE: no SAR token in env/.env …` | Fill in `SAR_TOKEN_NAME` / `SAR_TOKEN_PASS_CODE` (step 5), run again |

> Always install with `make setup`. A plain `uv sync` removes Pegasus.

---

## 7. Sign in to CORTEX (DevKit only)

Skip if `CORTEX_AUTH=api_key`.

```bash
make cortex-login
```

**Expected:** a browser opens for SSO; the command ends without an error. The token is stored in the
OS keychain (macOS Keychain, Windows Credential Manager, Linux keyring). Repeat when judges fail with
an authentication error.

> **WSL:** if no browser opens, copy the URL printed in the terminal into a Windows browser.

---

## 8. Verify the installation

```bash
make doctor
make test
```

**Expected:**

- `make doctor` ends with `All good.` Fix every `[FAIL]` line and run it again.
  `[WARN] pegasus` is acceptable (judges then run on DeepEval).
- `make test` ends with `… passed` and no `failed`. A failure on a fresh checkout is a code
  defect — report it.

| `make doctor` line | If not `[OK  ]` |
|---|---|
| `env files` | Run from the `ai-eval-suite` folder; complete step 4 |
| `deepeval` | `make setup` |
| `pegasus` | Step 6 |
| `certificates` | Fix the `CA_BUNDLE` path, or use `VERIFY_TLS=false` |
| `CORTEX_AUTH` / `CORTEX_HOST` / `CorteX DevKit` | Step 5, or step 7 for DevKit |
| `CORTEX call` | See [Troubleshooting](#11-troubleshooting); the line shows the URL called |

---

## 9. First run — offline

Replays the saved traces with deterministic checks only. No agent, no CORTEX, no network.

```bash
make run AGENT=knowledge_agent SUITE=sanity OFFLINE=1 JUDGES=0
```

**Expected:**

```
PASS  TC_002  [5 skipped]
PASS  TC_012  [5 skipped]
2 passed, 0 failed, 0 errors  ->  outputs/runs/<run id>/results.json
```

`skipped` = the check has no golden data for these cases, or does not apply. It is not a failure.

---

## 10. First run — live

Run in order. Each command adds one service, so a failure points to that service.

| # | Command | Adds | Expected |
|---|---|---|---|
| 1 | `make run AGENT=knowledge_agent SUITE=sanity JUDGES=0` | Agent | Both cases evaluated, no `ERROR` (10–60 s per case) |
| 2 | `make run AGENT=knowledge_agent SUITE=sanity` | CORTEX judges, Athena | Judge lines such as `PASS judge:relevance score=0.86/0.7 [pegasus]` |
| 3 | `make fields AGENT=knowledge_agent CASE=TC_002` | — | Every field read from the trace; key fields not `NOT FOUND` |
| 4 | `make dashboard` | — | http://localhost:8501 shows the run (stop with `Ctrl+C`) |

`FAIL` = a result about the agent. `ERROR` = a setup problem: see Troubleshooting.

**Setup is complete.** Next: [README.md](README.md) for everyday commands.

---

## 11. Troubleshooting

Run `make doctor` first: it checks most of these and prints the URL it called.

| Symptom | Fix |
|---|---|
| `make: *** No rule to make target …` | Run from the `ai-eval-suite` folder |
| `make: command not found` | Step 2 for your platform; reopen the terminal |
| `uv: command not found` | Reopen the terminal (the installer updates `PATH`) |
| `No module named '…'` | `git pull`, then `make setup` |
| `[WARN] pegasus … not installed` | SAR token in `env/.env`, VPN on, `make setup` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | `VERIFY_TLS=false`, or `CA_BUNDLE=<corporate CA file>` |
| CORTEX `401` / `403` | Wrong or expired `CORTEX_API_KEY` / `CORTEX_CLIENT_ID`; DevKit: `make cortex-login` |
| CORTEX `404` | `CORTEX_HOST` must end in `/v1`; compare with the URL in the error |
| CORTEX `429` | Rate limited; it retries. Run fewer cases: `CASE="TC_002"` |
| Case `ERROR`: connection refused / timed out | Check `KNOWLEDGE_ADK_BASE_URL`, VPN, agent environment status |
| Case `ERROR`: `get_page_content_from_athena(<id>) failed` | Check `HIVE_ATHENA_CLIENT_ID` / `_SECRET` / `_BASE_URL` |
| `.git/index.lock` exists | No git command running? Delete the file |
| **Windows:** `$'\r': command not found` or `bad interpreter` | Line endings: `git config --global core.autocrlf input`, then re-clone |
| **Windows:** a file path is not found | Use forward slashes. Git Bash: `FILE="/c/Users/<you>/Downloads/golden.xlsx"`. WSL: `FILE="/mnt/c/Users/<you>/Downloads/golden.xlsx"` |
| **WSL:** very slow commands | Move the repository from `/mnt/c/...` to `~/` |
| **WSL:** no network to bank services | Some VPN clients do not route WSL traffic; use Git Bash, or ask IT to enable WSL VPN routing |

More: [README.md → Troubleshooting](README.md#troubleshooting).
