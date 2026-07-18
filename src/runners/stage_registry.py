"""
Registry of (agent, stage) -> evaluator class. The single place a new stage
evaluator gets wired in - add one entry here, nothing else changes.
"""

import importlib

STAGE_EVALUATORS = {
    ("knowledge_agent", "stage1_query_rewrite"): (
        "src.evaluators.knowledge_agent.stage1_query_rewrite",
        "Stage1QueryRewriteEvaluator",
    ),
}


def load_evaluator_class(agent: str, stage: str):
    key = (agent, stage)
    if key not in STAGE_EVALUATORS:
        available = ", ".join(f"{a}/{s}" for a, s in STAGE_EVALUATORS) or "(none registered)"
        raise SystemExit(f"No stage evaluator for agent={agent!r}, stage={stage!r}. Available: {available}")
    module_path, class_name = STAGE_EVALUATORS[key]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
