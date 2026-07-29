#!/usr/bin/env python3
"""
Scaffold a minimal agent pack for ai-eval-suite.

  python3 scripts/new_agent.py --name my_agent
  make new-agent name=my_agent

Creates:
  - configs/agents.yaml entry
  - configs/metrics/<agent>/catalog.yaml
  - configs/evaluations/<agent>/sanity.yaml (+ optional sanity_pegasus.yaml)
  - testdata/<agent>/sanity/TC_001.json
  - tests/<agent>/conftest.py + test_sanity.py
  - makefiles/<agent>.mk

No custom parser — teams add enrich/parsers later if needed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new eval-suite agent pack.")
    parser.add_argument(
        "--name",
        required=True,
        help="Agent name in snake_case (e.g. my_agent). Used as folder + agents.yaml key.",
    )
    parser.add_argument(
        "--message-field",
        default="question",
        help="ADK message field / case input key (default: question).",
    )
    parser.add_argument(
        "--with-pegasus",
        action="store_true",
        default=True,
        help="Also scaffold sanity_pegasus suite (default: on).",
    )
    parser.add_argument(
        "--no-pegasus",
        action="store_true",
        help="Skip Pegasus suite files.",
    )
    args = parser.parse_args()

    name = args.name.strip()
    if not SNAKE_RE.match(name):
        print(
            f"error: name must be snake_case like 'my_agent', got {name!r}",
            file=sys.stderr,
        )
        return 1

    message_field = args.message_field.strip() or "question"
    with_pegasus = args.with_pegasus and not args.no_pegasus
    env_prefix = name.upper()

    conflicts = _existing_paths(name)
    if conflicts:
        print("error: refuse to overwrite existing paths:", file=sys.stderr)
        for path in conflicts:
            print(f"  - {path}", file=sys.stderr)
        return 1

    created: list[Path] = []
    created.append(_append_agents_yaml(name, message_field, env_prefix))
    created.append(_write_metric_catalog(name, message_field, with_pegasus))
    created.append(_write_sanity_suite(name))
    if with_pegasus:
        created.append(_write_sanity_pegasus_suite(name))
    created.append(_write_sample_case(name, message_field))
    created.append(_write_conftest(name, message_field))
    created.append(_write_test_sanity(name, message_field))
    created.append(_write_makefile(name, env_prefix))

    print(f"Scaffolded agent pack: {name}\n")
    for path in created:
        print(f"  created {path.relative_to(ROOT)}")
    print(
        f"""
Next steps:
  1. Set ADK env vars (see makefiles/{name}.mk comments), e.g.
       {env_prefix}_ADK_BASE_URL=...
       {env_prefix}_ADK_APP_NAME={name}
  2. Edit testdata/{name}/sanity/TC_001.json (input + optional expected_answer)
  3. Smoke without judges:
       make test-{name}-sanity
  4. With DeepEval judges:
       make test-{name}-sanity-judges
"""
        + (
            f"  5. With Pegasus judges:\n       make test-{name}-sanity-pegasus-judges\n"
            if with_pegasus
            else ""
        )
        + """
Optional later: add src/parsers/<agent>/ + deterministic checks when traces need it.
"""
    )
    return 0


def _existing_paths(name: str) -> list[Path]:
    found: list[Path] = []
    for path in (
        ROOT / "configs" / "metrics" / name,
        ROOT / "configs" / "evaluations" / name,
        ROOT / "testdata" / name,
        ROOT / "tests" / name,
        ROOT / "makefiles" / f"{name}.mk",
    ):
        if path.exists():
            found.append(path)

    agents = ROOT / "configs" / "agents.yaml"
    if agents.is_file():
        text = agents.read_text(encoding="utf-8")
        if re.search(rf"(?m)^\s+{re.escape(name)}\s*:", text):
            found.append(agents)
    return found


def _append_agents_yaml(name: str, message_field: str, env_prefix: str) -> Path:
    path = ROOT / "configs" / "agents.yaml"
    block = f"""
  {name}:
    metrics_profile: {name}
    app_name: ${{{env_prefix}_ADK_APP_NAME:-{name}}}
    user_id: ${{{env_prefix}_ADK_USER_ID:-eval_user}}
    base_url: ${{{env_prefix}_ADK_BASE_URL:-http://localhost:8080}}
    base_path: ${{{env_prefix}_ADK_BASE_PATH:-}}
    message_field: {message_field}
    timeout_s: 180
    verify_tls: false
    max_retries: 2
    headers: {{}}
"""
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + block, encoding="utf-8")
    return path


def _write_metric_catalog(name: str, message_field: str, with_pegasus: bool) -> Path:
    path = ROOT / "configs" / "metrics" / name / "catalog.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    pegasus_block = ""
    if with_pegasus:
        pegasus_block = f"""
  # Pegasus twins (select via METRICS_SUITE=sanity_pegasus)
  relevance_pegasus:
    type: relevance
    mode: ${{METRIC_MODE:-pegasus}}
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer

  correctness_pegasus:
    type: answer_correctness
    mode: ${{METRIC_MODE:-pegasus}}
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer
    expected_source: expected_answer

  faithfulness_pegasus:
    type: faithfulness
    mode: ${{METRIC_MODE:-pegasus}}
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer
    context_source: retrieval_context
"""
    path.write_text(
        f"""# {name} — starter metric catalog.
# Suites under configs/evaluations/{name}/ only select names from here.
default_suite: sanity

metrics:
  relevance:
    type: relevance
    mode: deepeval
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer

  correctness:
    type: correctness
    mode: deepeval
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer
    expected_source: expected_answer

  faithfulness:
    type: faithfulness
    mode: deepeval
    threshold: 0.7
    input_source: {message_field}
    actual_source: answer
    context_source: retrieval_context
{pegasus_block}""",
        encoding="utf-8",
    )
    return path


def _write_sanity_suite(name: str) -> Path:
    path = ROOT / "configs" / "evaluations" / name / "sanity.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# {name} — starter sanity suite (DeepEval).
# correctness needs expected.expected_answer (DeepEval may soft-skip if absent).
suite: sanity

judges:
  - relevance
  - correctness
""",
        encoding="utf-8",
    )
    return path


def _write_sanity_pegasus_suite(name: str) -> Path:
    path = ROOT / "configs" / "evaluations" / name / "sanity_pegasus.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# {name} — Pegasus sanity suite.
# Cases need fields each metric requires (MetricContractError if missing).
# Starter: relevance only (question + answer). Add others when data is ready.
suite: sanity_pegasus

judges:
  - relevance_pegasus
""",
        encoding="utf-8",
    )
    return path


def _write_sample_case(name: str, message_field: str) -> Path:
    path = ROOT / "testdata" / name / "sanity" / "TC_001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep JSON simple; teams replace placeholder text.
    sample_input = "Replace with a real question for your agent."
    if message_field != "question":
        sample_input = f"Replace with a real {message_field} value."
    path.write_text(
        f"""{{
  "test_case_id": "TC_001",
  "description": "Starter sanity case for {name}",
  "input": {{
    "{message_field}": "{sample_input}"
  }},
  "expected": {{
    "expected_answer": "Optional SME golden — used by correctness judges when present."
  }}
}}
""",
        encoding="utf-8",
    )
    return path


def _write_conftest(name: str, message_field: str) -> Path:
    path = ROOT / "tests" / name / "conftest.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''"""{name} fixtures — case loading / validation."""

from __future__ import annotations

import os

import pytest

from tests.support.sanity import load_sanity_cases

AGENT = "{name}"
METRICS_SUITE = os.environ.get("METRICS_SUITE", "sanity")

CASES = load_sanity_cases(AGENT, required_input_keys=["{message_field}"])
CASE_IDS = [c["test_case_id"] for c in CASES]


@pytest.fixture(params=CASES, ids=CASE_IDS)
def case(request: pytest.FixtureRequest) -> dict:
    return request.param
''',
        encoding="utf-8",
    )
    return path


def _write_test_sanity(name: str, message_field: str) -> Path:
    path = ROOT / "tests" / name / "test_sanity.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''"""
{name} — smoke run + optional suite judges.

  EVAL_MODE=live|cache
  RUN_JUDGES=true
  METRICS_SUITE=sanity|sanity_pegasus

  make test-{name}-sanity
  make test-{name}-sanity-judges
"""

from __future__ import annotations

from src.core.exceptions import AgentInvocationError
from src.models.agent_response import AgentResponse
from src.runners.case_runner import eval_mode, judges_enabled, run_case
from src.runners.evaluate import CheckResult, evaluate
from tests.{name}.conftest import AGENT, METRICS_SUITE
from tests.support.sanity import (
    DATA_SUITE,
    OUTPUT_DIR,
    assert_all_passed,
    check,
    publish_case,
)


def _prepare_for_judges(case: dict, response: AgentResponse) -> AgentResponse:
    """Attach question / optional golden for DeepEval + Pegasus (no custom parser)."""
    inp = case.get("input") or {{}}
    expected = case.get("expected") or {{}}
    prompt = str(inp.get("{message_field}") or "")
    golden = str(expected.get("expected_answer") or expected.get("answer") or "").strip()

    meta = dict(response.metadata or {{}})
    meta["question"] = prompt or str(meta.get("question") or "")
    meta["{message_field}"] = prompt
    if golden:
        meta["expected_answer"] = golden
        meta["reference_answer"] = golden
    contexts = list(response.context or [])
    if contexts:
        meta["retrieved_contexts"] = contexts
        meta.setdefault("retrieval_context", contexts)
    return response.model_copy(update={{"metadata": meta}})


def _run_deterministic(case: dict, response: AgentResponse) -> list[CheckResult]:
    prompt = str((case.get("input") or {{}}).get("{message_field}") or "")
    return [
        check("input_present", bool(prompt.strip()), "case input.{message_field} required"),
        check("answer_non_empty", bool((response.answer or "").strip()), "empty agent answer"),
    ]


def test_run_case(case: dict) -> None:
    mode = eval_mode()
    try:
        result = run_case(AGENT, case, DATA_SUITE, output_dir=OUTPUT_DIR, mode=mode)
    except AgentInvocationError as exc:
        import pytest

        pytest.skip(f"ADK not reachable: {{exc}}")
    except FileNotFoundError as exc:
        import pytest

        pytest.skip(str(exc))

    det = _run_deterministic(case, result.response)
    response = _prepare_for_judges(case, result.response)
    judges: list = []
    if judges_enabled():
        judges = evaluate(AGENT, METRICS_SUITE, case, response, publish=False).judges

    publish_case(
        agent=AGENT,
        suite=METRICS_SUITE,
        case=case,
        response=response,
        deterministic=det,
        judges=judges,
    )
    assert_all_passed(det, label="deterministic")
    assert_all_passed(judges, label="judges")
''',
        encoding="utf-8",
    )
    return path


def _write_makefile(name: str, env_prefix: str) -> Path:
    path = ROOT / "makefiles" / f"{name}.mk"
    path.write_text(
        f"""# {name} test targets (auto-included from root Makefile).
#
# Env (typical):
#   {env_prefix}_ADK_BASE_URL
#   {env_prefix}_ADK_APP_NAME
#   {env_prefix}_ADK_USER_ID

.PHONY: test-{name}-sanity test-{name}-sanity-cache test-{name}-sanity-judges \\
	test-{name}-sanity-pegasus test-{name}-sanity-pegasus-judges

test-{name}-sanity:
	EVAL_MODE=live pytest tests/{name}/test_sanity.py -v -s

test-{name}-sanity-cache:
	EVAL_MODE=cache pytest tests/{name}/test_sanity.py -v -s

test-{name}-sanity-judges:
	RUN_JUDGES=true EVAL_MODE=live pytest tests/{name}/test_sanity.py -v -s

METRIC_MODE ?= pegasus

test-{name}-sanity-pegasus:
	METRICS_SUITE=sanity_pegasus METRIC_MODE=$(METRIC_MODE) EVAL_MODE=live pytest tests/{name}/test_sanity.py -v -s

test-{name}-sanity-pegasus-judges:
	METRICS_SUITE=sanity_pegasus METRIC_MODE=$(METRIC_MODE) RUN_JUDGES=true EVAL_MODE=live pytest tests/{name}/test_sanity.py -v -s
""",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    raise SystemExit(main())
