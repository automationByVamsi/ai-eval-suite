"""
Canonical judge-ready row shared by DeepEval and Pegasus.

DeepEval: attach aliases onto AgentResponse (catalog *_source).
Pegasus: use to_pegasus_row() column names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalSample:
    """One judge-ready sample built from a case + agent response."""

    question: str = ""
    answer: str = ""
    retrieved_contexts: list[str] = field(default_factory=list)
    reference_answer: str = ""
    # Optional concatenated ground-truth doc (e.g. Fact Find summarization).
    source_document: str = ""

    def to_pegasus_row(self) -> dict[str, Any]:
        """Pegasus RAG column names."""
        return {
            "question": self.question,
            "answer": self.answer,
            "retrieved_contexts": list(self.retrieved_contexts),
            "reference_answer": self.reference_answer,
        }

    def metadata_aliases(self) -> dict[str, Any]:
        """Names catalog *_source / resolve_field commonly look up."""
        out: dict[str, Any] = {
            "question": self.question,
            "retrieved_contexts": list(self.retrieved_contexts),
            "retrieval_context": list(self.retrieved_contexts),
        }
        if self.reference_answer:
            out["expected_answer"] = self.reference_answer
            out["reference_answer"] = self.reference_answer
        if self.source_document:
            out["source_document"] = self.source_document
            out["ground_truth_context"] = list(self.retrieved_contexts)
        return out
