"""Load env files and fill `${VAR}` placeholders in YAML.

Precedence: shell variables, then env/.env.<agent>, then env/.env. Importing this loads env/.env and TLS settings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from src.core import paths, tls
from src.core.exceptions import ConfigError

# Taken before any env file is read, so shell variables always win.
_SHELL_VARS = set(os.environ)

# ${NAME} or ${NAME:-default}
_PLACEHOLDER = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def load_env_file(path: Path) -> bool:
    """Copy one env file into os.environ, leaving shell variables alone. Returns False if the file is missing."""
    if not path.is_file():
        return False
    for key, value in dotenv_values(path).items():
        if value is not None and value.lstrip().startswith("#"):
            # python-dotenv keeps `KEY=   # comment` as the value; treat it as empty.
            value = ""
        if key not in _SHELL_VARS and value is not None:
            os.environ[key] = value
    return True


def load_shared_env() -> None:
    """Load env/.env, or the old root .env when env/.env doesn't exist."""
    if not load_env_file(paths.ENV_DIR / ".env"):
        load_env_file(paths.ROOT / ".env")


def load_agent_env(agent_name: str) -> None:
    """Load env/.env.<agent> if present, overriding env/.env.
    A sub-agent like a/b loads env/.env.a, then env/.env.a.b."""
    parts = agent_name.split("/")
    for depth in range(1, len(parts) + 1):
        load_env_file(paths.ENV_DIR / f".env.{'.'.join(parts[:depth])}")


def expand(value: Any) -> Any:
    """Fill ${VAR} / ${VAR:-default} in every string of a nested YAML structure.
    The default applies when VAR is unset or empty; unset with no default becomes ""."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1)) or m.group(2) or "", value)
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    return value


def require(name: str, error: type[Exception] = ConfigError) -> str:
    """Return a required variable's value; raises `error` (ConfigError by default) if it is not set."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise error(f"{name} is not set — add it to env/.env (see env/.env.example)")
    return value


load_shared_env()
tls.configure()
