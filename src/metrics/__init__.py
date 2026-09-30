"""
LLM-as-a-judge.

  library.py   which metrics exist: reads metric_library.yaml, checks metric settings in agent.yaml
               when an agent loads (before anything runs)
  judges.py    how one metric is scored for one case: picks Pegasus or DeepEval, runs it,
               turns the score into pass / fail / skip / error

To add, remove or re-map a built-in metric, edit metric_library.yaml — not these files.
"""
