"""An agent's domains (business areas) from agents/<agent>/domains.yaml, with their aliases.

Gives each domain its {domain_name}, {domain_path}, {domain} and {domain_folder} values for importers and synth.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.core.exceptions import ConfigError
from src.utils.text import slug

FILE = "domains.yaml"


def load_domains(agent_folder: Path) -> dict[str, dict[str, Any]]:
    """Return {official name: {"aliases": [...], "path": "..."}} from domains.yaml, or {} if there is none."""
    file = Path(agent_folder) / FILE
    if not file.is_file():
        return {}
    raw = yaml.safe_load(file.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: must map each official name to its aliases, e.g. 'Fraud: []'")
    domains = {}
    for name, spec in raw.items():
        spec = {"aliases": spec} if isinstance(spec, list) or spec is None else dict(spec)
        domains[str(name)] = {"aliases": [str(a) for a in spec.get("aliases") or []],
                              "path": str(spec.get("path") or _underscored(name))}
    return domains


def official_name(text: str, domains: dict[str, dict[str, Any]]) -> str | None:
    """Return the official name `text` matches (by name or alias, ignoring case and punctuation), or None."""
    wanted = _plain(text)
    for name, spec in domains.items():
        if wanted in {_plain(name), *map(_plain, spec["aliases"])}:
            return name
    return None


def domain_values(text: str, domains: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Return {domain, domain_folder, domain_name, domain_path} for a domain; unknown names keep their spelling."""
    name = official_name(text, domains) or str(text).strip()
    path = domains[name]["path"] if name in domains else _underscored(name)
    return {"domain": slug(name).upper(), "domain_folder": slug(name), "domain_name": name, "domain_path": path}


def no_domain(label: str) -> dict[str, str]:
    """Return domain values for a case with no business area: filed under `label`, nothing sent to the agent."""
    return {**domain_values(label, {}), "domain_name": "", "domain_path": ""}


def _underscored(name: str) -> str:
    """Return the name with spaces as underscores, e.g. Complaint_Managers."""
    return str(name).strip().replace(" ", "_")


def _plain(text: str) -> str:
    """Return text lowercased with everything but letters and digits removed, for matching."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())
