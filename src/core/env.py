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

# Prefer repo-root `.env`; also accept common office-machine locations.
_DEFAULT_ENV_CANDIDATES = (
    Path(".env"),
    Path("src/.env"),
    Path("env/.env.factfind.api"),
    Path(".env.factfind.api"),
)

# Working factfind/ai-evals + older local names → current ai-eval-suite names.
_ENV_ALIASES: tuple[tuple[str, str], ...] = (
    ("FACTFIND_ADK_BASE_URL", "ADK_BASE_HOST"),
    ("FACTFIND_ADK_APP_NAME", "ADK_APP_NAME"),
    ("FACTFIND_ADK_USER_ID", "ADK_USER_ID"),
    ("KNOWLEDGE_ADK_BASE_URL", "KNOWLEDGE_BASE_URL_LOCAL"),
    ("KNOWLEDGE_ADK_BASE_PATH", "KNOWLEDGE_BASE_PATH_LOCAL"),
    ("KNOWLEDGE_ADK_APP_NAME", "KNOWLEDGE_APP_NAME_LOCAL"),
    ("KNOWLEDGE_ADK_USER_ID", "KNOWLEDGE_USER_ID_LOCAL"),
)


def _load_env_file(env_path: Path) -> None:
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _apply_env_aliases() -> None:
    """Copy legacy / working-repo keys into the names agents.yaml expects."""
    for dest, src in _ENV_ALIASES:
        if dest not in os.environ and src in os.environ and os.environ[src].strip():
            os.environ[dest] = os.environ[src].strip()


def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ if the key is not already set."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = list(_DEFAULT_ENV_CANDIDATES)

    for env_path in candidates:
        if env_path.is_file():
            _load_env_file(env_path)

    _apply_env_aliases()


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
