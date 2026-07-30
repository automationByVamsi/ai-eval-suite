"""
Shared eval helpers (agent-agnostic).

One path for judges:

  response = parsers.<agent>.prepare_response(case, response)
  response = prepare_sample(case, response)
  evaluate(agent, suite, case, response)

EvalSample is the shared row for DeepEval + Pegasus.
"""

from src.eval.prepare import prepare_sample
from src.eval.sample import EvalSample

__all__ = [
    "EvalSample",
    "prepare_sample",
]
