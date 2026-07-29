"""Pegasus metric strategy — what class to call and which fields are required."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PegasusStrategy:
    """
    One Pegasus RAG metric.

    Factory matches catalog type/name → strategy.
    Runner builds the required row, checks contract, calls pegasus_class.
    """

    # Catalog type values that select this strategy (exact match).
    type_keys: frozenset[str]
    # Substrings in metric name that select this strategy (e.g. "correctness").
    name_contains: tuple[str, ...]
    # Class name under pegasus.metrics.rag (e.g. "Faithfulness").
    pegasus_class: str
    # Always-required DataFrame columns (Pegasus names).
    required: tuple[str, ...]
    # Extra required columns when method is e.g. "ragas".
    required_by_method: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # If set, coerce method to first allowed when catalog mode is unsupported.
    allowed_methods: frozenset[str] | None = None
    # Default catalog name when cfg has no name.
    default_name: str = ""

    def matches(self, mtype: str, name: str) -> bool:
        if mtype in self.type_keys:
            return True
        return any(token in name for token in self.name_contains)
