"""
Output template: turn one generated question/answer into the agent's test case JSON.

The template is `output:` in synth.yaml (folder, id, case). Any part an agent leaves out comes
from default_output() — the standard evaluation test case. Strings can hold placeholders:

  {generated.input}             the generated question (or input)
  {generated.expected_output}   the generated reference answer
  {generated.input.request}     a field of the generated input, when a style asks for JSON input
  {source.id} {source.title} {source.text} {source.metadata.revision}   the document
  {style} {group} {group_slug}  the style name, the document's group, and group as a folder name
  {run.id} {run.date} {run.generated_at} {run.model}                  this generation run
  {agent.name} {agent.input_field}
  {id} {n}                      the case id, and its number (format like {n:03} -> 001)

A string that is exactly one placeholder keeps the value's type (e.g. a list stays a list).
If the generated text lacks a field the template asks for, that case is skipped (and listed
in the run manifest) instead of being written half-empty.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.core.agent_config import Agent
from src.core.exceptions import ConfigError
from src.utils.text import safe_filename, slug, strip_code_fence

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.]*)(?::([^{}]*))?\}")
_ROOTS = ("generated", "source", "style", "group", "group_slug", "run", "agent", "id", "n")
_MAX_NUMBER = 9999


class MissingGenerated(Exception):
    """The generated text doesn't contain a field the template asks for — the case is skipped."""


def default_output(agent: Agent) -> dict[str, Any]:
    """The standard test case shape, used for any part of `output:` an agent leaves out."""
    return {
        "folder": "testdata/golden/{style}/{group_slug}",
        "id": "SYN_{style}_{group_slug}_{n:03}",
        "case": {
            "test_case_id": "{id}",
            "description": "Generated ({style}) from {source.id} {source.title}",
            "input": {agent.input_field: "{generated.input}"},
            "expected": {"expected_answer": "{generated.expected_output}", "source_id": "{source.id}"},
            "metadata": {"origin": "SYNTHETIC", "approval_status": "UNREVIEWED", "style": "{style}",
                         "group": "{group}", "generation_run_id": "{run.id}",
                         "generated_at": "{run.generated_at}", "generator_model": "{run.model}"},
        },
    }


def render_case(agent: Agent, output: dict[str, Any], run: dict[str, Any], style: str,
                document: dict[str, Any], golden: Any, taken: set[Path], replace: bool
                ) -> tuple[Path, dict[str, Any]]:
    """
    (file path, case JSON) for one generated golden.

    Numbering: {n} counts up from 1 until the id is free — not used earlier in this run and, unless
    REPLACE=1, not already on disk. So re-running adds new cases after the existing ones.
    """
    context = {
        "generated": {"input": golden.input, "expected_output": golden.expected_output or ""},
        "source": document, "style": style, "group": document["group"], "group_slug": slug(document["group"]),
        "run": run, "agent": {"name": agent.name, "input_field": agent.input_field},
    }
    folder = agent.folder / str(render(output["folder"], context))
    taken_ids = {p.stem for p in taken}
    for n in range(1, _MAX_NUMBER + 1):
        case_id = str(render(output["id"], {**context, "n": n}))
        path = folder / f"{safe_filename(case_id)}.json"
        if path not in taken and path.stem not in taken_ids and (replace or not path.exists()):
            return path, render(output["case"], {**context, "n": n, "id": case_id})
    raise ConfigError(f"Output template id '{output['id']}' never gives a free name — include {{n}} in it")


def render(template: Any, context: dict[str, Any]) -> Any:
    """Fill {placeholders} in every string of a template (dicts and lists included)."""
    if isinstance(template, dict):
        return {key: render(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render(value, context) for value in template]
    if not isinstance(template, str):
        return template
    whole = _PLACEHOLDER.fullmatch(template)
    if whole and not whole.group(2):
        return _lookup(whole.group(1), context)
    return _PLACEHOLDER.sub(lambda m: format(_lookup(m.group(1), context) or "", m.group(2) or ""), template)


def _lookup(path: str, context: dict[str, Any]) -> Any:
    """The value of one dotted placeholder, e.g. 'source.metadata.revision'."""
    root, *rest = path.split(".")
    if root not in _ROOTS:
        raise ConfigError(f"Output template: unknown placeholder '{{{path}}}'. Start with one of {list(_ROOTS)}")
    value = context.get(root)
    for part in rest:
        if isinstance(value, str):
            # The generated text was asked to be JSON, e.g. {generated.input.request}.
            try:
                value = json.loads(strip_code_fence(value))
            except json.JSONDecodeError:
                value = None
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif root == "generated":
            raise MissingGenerated(f"generated text has no '{path}'")
        else:
            return None            # optional details, e.g. a source without metadata.revision
    return value
