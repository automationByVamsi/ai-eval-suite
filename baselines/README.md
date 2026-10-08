# Baselines

Two files per agent and suite, written by `make baseline`:

- `<suite>.json` — per case and per check / judge: pass rate and mean score (what `make verdict` compares)
- `<suite>.run.json` — the whole baseline run: every case's answer, pages, scores and reasons (what the
  dashboard's verdict view shows as the "Baseline build")

Commit both so everyone compares new builds against the same stable build. Git history keeps the older
baselines.
