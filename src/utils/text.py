"""Text helpers shared by the judges, the CORTEX client and the synthesizer."""

from __future__ import annotations

import re
from typing import Any


def strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence (Gemini often wraps JSON answers in one)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def slug(text: str) -> str:
    """Return a lowercase underscore slug for folder and id names, e.g. 'Commercial Bank' -> 'commercial_bank'."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "unassigned"


def safe_filename(text: str) -> str:
    """Return text made safe as a file name (keeps letters, digits, _ . -)."""
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_")


def normalised(text: str) -> str:
    """Return text lowercased with single spaces, for spotting duplicates."""
    return " ".join((text or "").lower().split())


def is_empty(value: Any) -> bool:
    """True for None, blank strings, and lists that contain only blank values."""
    if isinstance(value, (list, tuple)):
        return not any(str(v).strip() for v in value)
    return not str(value if value is not None else "").strip()


def first(value: Any) -> Any:
    """Return the first element of a list, tuple or pandas column; other values unchanged."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value
