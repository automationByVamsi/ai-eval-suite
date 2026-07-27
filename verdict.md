# VERDICT — A Reliability Engine for the Knowledge Agent's Evaluation

## The Problem

The Knowledge Agent is a chained, non-deterministic system. Every stage — query rewrite, search, anchor selection, relation expansion, validation, synthesis — makes an LLM-driven decision that feeds the next. The existing HIVE evaluation framework already recognizes the hard part of this: a final answer can be fluent, relevant, and faithful to the evidence it received, and still be wrong because an earlier stage silently retrieved or expanded the wrong evidence. End-to-end checks go green; the pipeline made a bad decision three stages upstream; the user never knows.

HIVE addresses this well with stage-wise contracts: Layer 1 deterministic validation, Layer 2 LLM-as-a-Judge, and a Golden Dataset benchmark. That specification is strong. But three gaps remain — and they are exactly the gaps that let a broken build reach production looking healthy.

**Gap 1 — The judges are never validated.** All of Layer 2 rests on GEval/DeepEval metrics with thresholds like "intent preservation ≥ 0.85" or "context relevance ≥ 0.70." Nothing measures whether the judge's 0.85 agrees with what a subject-matter expert would actually say. The framework puts thresholds *on* the judge's output, but never measures the judge's own trustworthiness. To a reviewer, every Layer 2 number is one model grading another model, with no known error rate.

**Gap 2 — Single-run scoring on a non-deterministic pipeline.** Because every stage is LLM-driven, running the same golden scenario twice can produce a different anchor or a different expansion set. The current matrices score one trace. So "Anchor Accuracy: PASS" might mean 95%-of-the-time correct, or it might be a lucky coin flip observed once. A single pass/fail hides the flakiness that defines an LLM pipeline.

**Gap 3 — No regression gate on stage-level behavior.** Release readiness is defined ("100% Layer 1 pass," "thresholds per suite"), but there is no mechanism that catches *"this candidate build dropped Expansion Coverage from 91% to 68% versus the last release."* A prompt tweak or a threshold change can silently regress a stage, and nothing compares the new build's behavior to the last trusted one. The regression surfaces only when a user hits it.

The cost of these gaps is the exact failure the HIVE document itself illustrates: the "domestic abuse" query where relation expansion dropped a required companion page, validation marked the incomplete context as sufficient, synthesis stayed faithful to that incomplete evidence, and every end-to-end signal passed. Green board, wrong answer, no alert.

---

## What VERDICT Is

VERDICT is a reliability engine that wraps around the existing HIVE evaluation — it does not replace it and does not touch the Knowledge Agent's code. HIVE defines *what "good" means* at each stage. VERDICT runs those contracts repeatedly, interprets the results honestly, validates the judges doing the grading, and catches the day a change quietly breaks something. It consumes what the agent already emits — traces, tool responses, stage outputs, and the golden dataset — consistent with the separate-repo, oracle-recall constraint the framework already operates under.

In one line: **HIVE tells us what good means at each stage; VERDICT tells us whether we can trust the tool that decides that — and catches the day a change silently breaks it before the user sees it.**

---

## How VERDICT Helps

**It turns single scores into distributions.** Instead of scoring one trace, VERDICT runs each golden scenario many times and reports every stage metric as a value with its variance — "Anchor Accuracy 94% ± 3%" instead of a lone "PASS." This is the honest picture for a non-deterministic pipeline, and it exposes instability that a single run hides by luck. *(Closes Gap 2.)*

**It gates releases on regressions, not just thresholds.** VERDICT saves the behavior of the last trusted release as a baseline and diffs each new build against it, flagging any stage whose pass rate dropped beyond run-to-run noise. Because it compares distributions, it separates a real regression from normal flakiness. The threshold-change-that-drops-expansion-coverage gets caught here — three stages before the user, on a scenario no human was watching. *(Closes Gap 3.)*

**It validates the judges.** VERDICT measures each Layer 2 metric against SME-labelled examples and reports how well the judge agrees with the experts — precision, recall, and Cohen's κ per metric. Every threshold then carries a known error rate. "Context relevance ≥ 0.70" stops being an assertion and becomes a measurement: "this judge agrees with our SMEs at κ = 0.83." This is the difference between a framework that *claims* quality and one that can *prove* the thing measuring quality is itself trustworthy. *(Closes Gap 1.)*

**It explains failures automatically.** When a regression is flagged, VERDICT produces a root-cause note that localizes the failure to a stage, identifies the mechanism, traces the downstream effect, and recommends a fix — automating the manual attribution the HIVE document does by hand in the DAFAT example. This is the operational form of the framework's own thesis: stage-wise evaluation doesn't just measure the pipeline, it *explains* it.

---

## Worked Example — The DAFAT Case, Through VERDICT

Take the exact scenario from the HIVE document: query "domestic abuse," where the required DAFAT referral companion page is silently dropped.

**What end-to-end evaluation reported:** answer relevancy PASS, faithfulness PASS, overall PASS. Green. Ships.

**What VERDICT surfaces instead:**

Running the scenario 20× and diffing against the last release baseline:

| Stage | Metric | Baseline | This build | Verdict |
|---|---|---|---|---|
| Anchor | Anchor Accuracy | 100% | 100% | ok |
| Expansion | Expansion Coverage | 96% | **41%** | 🔴 regression |
| Validation | Routing correct | 98% | 97% | ok |
| Synthesis | Fact Coverage | 95% | **44%** | 🔴 downstream |

The single sampled trace passed because the answer was fluent and grounded. The distribution reveals that 41% of the time expansion drops the companion page, and Fact Coverage collapses in lockstep — the correlation is the fingerprint of an upstream cause. The baseline diff localizes it to relation expansion. The calibrated judge means the "this page was relevant" signal carries a measured confidence, not just a model's opinion. And the root-cause note explains why: the companion page is a contextual relationship that passes through a score-based gate; a threshold raised from 0.70 to 0.78 in this build excluded it in most runs; validation still routed FINISH because low sufficiency doesn't force a FAIL; downstream fact coverage fell as a direct result.

None of that is visible to end-to-end evaluation. All of it is visible to VERDICT — before release.

---

## Where VERDICT Sits

- **HIVE** — the contract specification: what to check at each stage. Unchanged.
- **DeepEval / GEval** — the runner and metric primitives. Reused as-is.
- **VERDICT** — the reliability engine around both: distributions instead of single scores, baseline diffing for regression detection, judge calibration for trust, and automated root-cause attribution.

VERDICT is not another thing that produces answers. It is the layer that decides whether the pipeline that produces them — and the evaluation that grades them — can be trusted release over release.

---

## Try it (v0 in this repo)

Agent-agnostic: pick any registered agent (`knowledge_agent`, `fact_find_workflow`, …).
Uses that agent’s **sanity** suite + saved traces under `outputs/traces/<agent>/sanity/`.
Deterministic sanity checks (answer / keywords) by default; optional judges with `--judges`.

```bash
# Knowledge Agent demo
make verdict-demo AGENT=knowledge_agent

# Fact Find
make verdict-check AGENT=fact_find_workflow

# or:
#   python3 -m scripts.run_verdict --agent knowledge_agent --n 5 --save-baseline --no-compare
#   python3 -m scripts.run_verdict --agent knowledge_agent --n 5 --simulate-regression
#   python3 -m scripts.run_verdict --agent fact_find_workflow --n 5

# Dashboard
make verdict-dashboard
```

Optional judge resampling (needs CORTEX): `make verdict-judges AGENT=…`

New agent: add a small adapter under `src/verdict/adapters/` and `register(AgentPack(...))`.
Stage-wise KA contracts are deferred — rewrite later under parsers/ when ready.
