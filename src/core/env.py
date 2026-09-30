"""
Settings from env files, and `${VAR}` placeholders in YAML.

Where values come from, strongest first:
  1. variables already set in your shell (CI sets them this way) — never overridden
  2. env/.env.<agent>   optional, one agent's values; loaded when that agent is loaded
  3. env/.env           shared values: CORTEX, Athena, every agent's URL ...
     (.env in the repo root is still read if env/.env doesn't exist — the old location)

env/.env.example lists every variable. `make setup` copies it to env/.env.

Importing this module loads env/.env once, so every command sees the shared values, and then
applies the HTTPS certificate settings (src/core/tls.py).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from src.core import paths, tls
from src.core.exceptions import ConfigError

# Taken before any env file is read: whatever is in here came from the shell and always wins.
_SHELL_VARS = set(os.environ)

# ${NAME} or ${NAME:-default}
_PLACEHOLDER = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def load_env_file(path: Path) -> bool:
    """Copy one env file into os.environ (shell variables are left alone). False if the file doesn't exist."""
    if not path.is_file():
        return False
    for key, value in dotenv_values(path).items():
        if value is not None and value.lstrip().startswith("#"):
            # `KEY=      # a comment` — python-dotenv keeps the comment as the value. It means "empty".
            value = ""
        if key not in _SHELL_VARS and value is not None:
            os.environ[key] = value
    return True


def load_shared_env() -> None:
    """env/.env, or the old root .env when env/.env doesn't exist yet."""
    if not load_env_file(paths.ENV_DIR / ".env"):
        load_env_file(paths.ROOT / ".env")


def load_agent_env(agent_name: str) -> None:
    """env/.env.<agent>, if there is one. Its values override env/.env."""
    load_env_file(paths.ENV_DIR / f".env.{agent_name}")


def expand(value: Any) -> Any:
    """
    Fill ${VAR} / ${VAR:-default} in every string of a YAML structure (dicts and lists included).

    Like the shell, the default is used when VAR is unset *or empty*, and an unset VAR with no
    default becomes "" — so a missing URL shows up as a clear error where it is used.
    """
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1)) or m.group(2) or "", value)
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    return value


def require(name: str, error: type[Exception] = ConfigError) -> str:
    """The value of a variable that must be set, or `error` telling the user where to set it."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise error(f"{name} is not set — add it to env/.env (see env/.env.example)")
    return value


load_shared_env()
tls.configure()      # HTTPS certificate settings (VERIFY_TLS / CA_BUNDLE) — see src/core/tls.py
