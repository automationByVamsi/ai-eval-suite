"""Text helpers shared by the judges, the CORTEX client and the synthesizer."""

from __future__ import annotations

import re
from typing import Any


def strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence. Gemini often wraps JSON answers in one."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def slug(text: str) -> str:
    """'Recoveries Commercial Bank' -> 'recoveries_commercial_bank' (for folder and id names)."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "unassigned"


def safe_filename(text: str) -> str:
    """Anything -> a string that is safe as a file name (keeps letters, digits, _ . -)."""
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_")


def normalised(text: str) -> str:
    """Lower-case with single spaces — used to spot duplicate questions."""
    return " ".join((text or "").lower().split())


def is_empty(value: Any) -> bool:
    """True for None, blank strings, and lists that contain only blank values."""
    if isinstance(value, (list, tuple)):
        return not any(str(v).strip() for v in value)
    return not str(value if value is not None else "").strip()


def first(value: Any) -> Any:
    """First element of a list / tuple / pandas column; other values are returned unchanged."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value
