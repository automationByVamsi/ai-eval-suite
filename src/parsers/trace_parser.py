"""Generic "load a captured trace JSON file off disk" helper, shared by every stage evaluator."""

import json
from pathlib import Path
from typing import Any

from src.core.exceptions import TraceParseError


def load_raw_trace(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise TraceParseError(f"Trace file not found: {path}")
    try:
        with path.open() as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise TraceParseError(f"Trace file is not valid JSON: {path} ({exc})") from exc
