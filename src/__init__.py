"""
ai-eval-suite: evaluate AI agents.

For every test case the framework
  1. calls the agent (Google ADK by default)      clients/adk_client.py
  2. saves the trace                              runners/suite_runner.py
  3. reads input / expected from the test case    runners/test_cases.py
  4. pulls fields out of the trace                agents/<agent>/fields.yaml -> fields/extract.py
  5. runs checks and LLM judges                   agents/<agent>/checks.yaml -> fields/checks.py;
                                                  metrics/  (Pegasus first, DeepEval otherwise)
  6. reports pass / fail                          reporting/
  7. compares the build with a baseline           verdict/

Folder map (read top to bottom the first time):

  cli.py          every `make` command lands here
  core/           paths, env files, agent.yaml loading, result types, errors
  clients/        talking to other systems: the agent (ADK), CORTEX (judge model), Athena
  runners/        the evaluation loop: test cases in, results out
  fields/         fields.yaml (what to read from traces), YAML checks, make fields (preview)
  importers/      spreadsheets -> test cases (make import-cases)
  metrics/        LLM judges: metric_library.yaml, engine choice, DeepEval and Pegasus scoring
  verdict/        baseline save + compare
  reporting/      console report and the Streamlit dashboard
  synthesizer/    generate test cases from documents (make sources / make goldens)
  onboarding/     make new-agent
  utils/          small helpers with no framework knowledge (ADK trace readers, text, HTML)

Onboarding an agent or changing metrics never needs a change in src/ — that's agents/<agent>/
and metric_library.yaml. The README has a "where do I change X" table.
"""
