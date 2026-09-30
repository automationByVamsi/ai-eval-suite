"""
LLM-as-a-judge.

  library.py          reads metric_library.yaml and validates metric settings in agent.yaml
  judge.py            scores one metric for one case: picks the engine, handles skip / error
  deepeval_judge.py   scoring with DeepEval (library metrics + custom rubrics via GEval)
  pegasus_judge.py    scoring with Pegasus (the team's standard RAG metrics)

To add, remove or re-map a built-in metric, edit metric_library.yaml — not these files.
"""
