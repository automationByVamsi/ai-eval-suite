"""
Turn one generated question/answer into the agent's test case JSON using the `output:` template.
Placeholders like {generated.input}, {source.id}, {group_slug}, {n:03} are filled; see _ROOTS for the allowed roots.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.core.agent_config import Agent
from src.core.domains import domain_values
from src.core.exceptions import ConfigError
from src.utils.text import safe_filename, slug, strip_code_fence

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.]*)(?::([^{}]*))?\}")
_ROOTS = ("generated", "source", "style", "group", "group_slug", "domain", "domain_folder", "domain_name",
          "domain_path", "question_type", "run", "agent", "id", "n")
_MAX_NUMBER = 9999


class MissingGenerated(Exception):
    """Raised when the generated text lacks a field the template needs; the case is skipped."""


def default_output(agent: Agent) -> dict[str, Any]:
    """Return the standard test case template, used for any part of `output:` an agent leaves out."""
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
                document: dict[str, Any], golden: Any, taken: set[Path], replace: Any,
                question_type: str = "", domains: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    """Return (file path, case JSON) for one golden; {n} counts up from 1 until the id is free.
    `replace` is False, True (overwrite anything), or a set of styles whose files may be reused."""
    context = {
        "generated": {"input": golden.input, "expected_output": golden.expected_output or ""},
        "source": document, "style": style, "group": document["group"], "group_slug": slug(document["group"]),
        **domain_values(document["group"], domains or {}),
        "question_type": question_type or "",
        "run": run, "agent": {"name": agent.name, "input_field": agent.input_field},
    }
    folder = agent.folder / str(render(output["folder"], context))
    taken_ids = {p.stem for p in taken}
    for n in range(1, _MAX_NUMBER + 1):
        case_id = str(render(output["id"], {**context, "n": n}))
        path = folder / f"{safe_filename(case_id)}.json"
        if path not in taken and path.stem not in taken_ids and _free(path, replace):
            case = render(output["case"], {**context, "n": n, "id": case_id})
            for part in ("input", "expected", "metadata"):  # drop empty values, e.g. question_type of a generic style
                if isinstance(case.get(part), dict):
                    case[part] = {k: v for k, v in case[part].items() if v not in ("", None, [])}
            return path, case
    raise ConfigError(f"Output template id '{output['id']}' never gives a free name — include {{n}} in it")


def _free(path: Path, replace: Any) -> bool:
    """Return True if a case may be written to `path` under the given `replace` mode."""
    if not path.exists() or replace is True:
        return True
    if not replace:
        return False
    try:
        return (json.loads(path.read_text()).get("metadata") or {}).get("style") in replace
    except (ValueError, OSError):
        return False


def render(template: Any, context: dict[str, Any], roots: tuple[str, ...] = _ROOTS) -> Any:
    """Fill {placeholders} in every string of a template; a lone placeholder keeps the value's type.
    `roots` are the allowed first parts of a placeholder (the spreadsheet importer passes its own)."""
    if isinstance(template, dict):
        return {key: render(value, context, roots) for key, value in template.items()}
    if isinstance(template, list):
        return [render(value, context, roots) for value in template]
    if not isinstance(template, str):
        return template
    whole = _PLACEHOLDER.fullmatch(template)
    if whole and not whole.group(2):
        return _lookup(whole.group(1), context, roots)
    return _PLACEHOLDER.sub(lambda m: format(_or_blank(_lookup(m.group(1), context, roots)), m.group(2) or ""),
                            template)


def _or_blank(value: Any) -> Any:
    """Map None or [] to "" inside a longer string; 0 stays 0 so {n:03} still works."""
    return "" if value is None or value == [] else value


def _lookup(path: str, context: dict[str, Any], roots: tuple[str, ...] = _ROOTS) -> Any:
    """Return the value of one dotted placeholder, e.g. 'source.metadata.revision'."""
    root, *rest = path.split(".")
    if root not in roots:
        raise ConfigError(f"Output template: unknown placeholder '{{{path}}}'. Start with one of {list(roots)}")
    value = context.get(root)
    for part in rest:
        if isinstance(value, str):
            # Generated text may be JSON, e.g. {generated.input.request}.
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
