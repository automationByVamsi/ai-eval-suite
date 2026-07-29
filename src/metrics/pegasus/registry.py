"""Registry of Pegasus strategies — add new metrics here."""

from __future__ import annotations

from src.metrics.pegasus.strategy import PegasusStrategy

# Order matters: first match wins (correctness before relevancy, etc.).
PEGASUS_STRATEGIES: tuple[PegasusStrategy, ...] = (
    PegasusStrategy(
        type_keys=frozenset({"answer_correctness", "correctness"}),
        name_contains=("correctness",),
        pegasus_class="AnswerCorrectness",
        required=("question", "answer", "reference_answer"),
        allowed_methods=frozenset({"pegasus", "ragas"}),
        default_name="answer_correctness",
    ),
    PegasusStrategy(
        type_keys=frozenset({"context_precision"}),
        name_contains=("context_precision",),
        pegasus_class="ContextPrecision",
        required=("question", "reference_answer", "retrieved_contexts"),
        default_name="context_precision",
    ),
    PegasusStrategy(
        type_keys=frozenset({"context_recall"}),
        name_contains=("context_recall",),
        pegasus_class="ContextRecall",
        required=("question", "answer", "reference_answer", "retrieved_contexts"),
        default_name="context_recall",
    ),
    PegasusStrategy(
        type_keys=frozenset({"relevance", "answer_relevancy"}),
        name_contains=("relevanc",),
        pegasus_class="AnswerRelevancy",
        required=("question", "answer"),
        required_by_method={"ragas": ("retrieved_contexts",)},
        default_name="answer_relevancy",
    ),
    PegasusStrategy(
        type_keys=frozenset({"faithfulness"}),
        name_contains=("faithfulness",),
        pegasus_class="Faithfulness",
        required=("question", "answer", "retrieved_contexts"),
        default_name="faithfulness",
    ),
)

# Fallback when type/name is unknown but mode is pegasus* (legacy default).
DEFAULT_STRATEGY = PEGASUS_STRATEGIES[-1]
