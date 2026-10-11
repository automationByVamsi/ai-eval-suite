"""
An agent's domains (for the Knowledge Agent: its 25 business areas), written once in
agents/<agent>/domains.yaml and used by the spreadsheet importer and the synthesizer, so every test case
names its domain the same way:

    Customer Vulnerability Hub: [CVH]        # official name: [other spellings seen in sheets / page_ids.json]
    Customer Financial Assistance (CFA):
      aliases: [CFA]
      path: Customer_Financial_Assistance_(CFA)     # only when the agent's value isn't the usual one

Each domain gives four values (the placeholders in import mappings and synth.yaml):

    {domain_name}    Customer Vulnerability Hub          the official name
    {domain_path}    Customer_Vulnerability_Hub          what the agent receives as business_area
    {domain}         CUSTOMER_VULNERABILITY_HUB          in test case ids
    {domain_folder}  customer_vulnerability_hub          test data folder

Names match ignoring case, spaces and punctuation ("customer_vulnerability_hub" = "Customer Vulnerability
Hub"). A name not in the list keeps its own spelling. No domain (an empty cell) -> {domain_path} is "", so
the case sends no business_area and the agent searches the whole knowledge base.
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
    """{official name: {"aliases": [...], "path": "..."}} from agents/<agent>/domains.yaml ({} if none)."""
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
    """The official name `text` stands for (its name or one of its aliases), or None."""
    wanted = _plain(text)
    for name, spec in domains.items():
        if wanted in {_plain(name), *map(_plain, spec["aliases"])}:
            return name
    return None


def domain_values(text: str, domains: dict[str, dict[str, Any]]) -> dict[str, str]:
    """{domain, domain_folder, domain_name, domain_path} for a domain as written in a sheet or page list."""
    name = official_name(text, domains) or str(text).strip()
    path = domains[name]["path"] if name in domains else _underscored(name)
    return {"domain": slug(name).upper(), "domain_folder": slug(name), "domain_name": name, "domain_path": path}


def no_domain(label: str) -> dict[str, str]:
    """For a case without a business area: filed under `label` (e.g. UNASSIGNED), nothing sent to the agent."""
    return {**domain_values(label, {}), "domain_name": "", "domain_path": ""}


def _underscored(name: str) -> str:
    """The agent's business_area: the name with spaces as underscores, e.g. Complaint_Managers."""
    return str(name).strip().replace(" ", "_")


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())
