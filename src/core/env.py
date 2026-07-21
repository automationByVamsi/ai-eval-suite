"""
Load gitignored `.env` and expand `${VAR}` / `${VAR:-default}` in config values.

Existing process env wins over `.env` (dotenv never overrides).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_DOTENV_LOADED = False


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines into os.environ if the key is not already set."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    env_path = Path(path)
    if not env_path.is_file():
        return

    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def expand_env_string(value: str) -> str:
    """Replace `${VAR}` and `${VAR:-default}` using os.environ."""

    def _repl(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2)
        if var_name in os.environ:
            return os.environ[var_name]
        if default is not None:
            return default
        return ""

    return _ENV_PATTERN.sub(_repl, value)


def expand_env(data: Any) -> Any:
    """Recursively expand env placeholders in strings inside YAML-loaded data."""
    if isinstance(data, str):
        return expand_env_string(data)
    if isinstance(data, list):
        return [expand_env(item) for item in data]
    if isinstance(data, dict):
        return {key: expand_env(value) for key, value in data.items()}
    return data
