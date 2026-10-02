"""
`make new-agent NAME=my_agent [INPUT_FIELD=question]`

Copies agents/_template/ to agents/<name>/ and fills in:
  - the agent name and its env variable names (MY_AGENT_BASE_URL -> <NAME>_BASE_URL, ...)
  - the input field in agent.yaml and in the sample test case
  - the agent's variables at the end of env/.env.example
then prints the next steps. To change what every new agent starts with, edit agents/_template/.
"""

from __future__ import annotations

import json
import re
import shutil

from src.core import paths
from src.core.exceptions import ConfigError


def create_agent(name: str, input_field: str = "question") -> None:
    """Create agents/<name>/ from the template. Refuses an existing folder or a non-snake_case name."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ConfigError(f"Agent name must be snake_case, like my_agent (got {name!r})")
    target = paths.AGENTS_DIR / name
    if target.exists():
        raise ConfigError(f"{target} already exists")

    shutil.copytree(paths.AGENTS_DIR / "_template", target)
    prefix = name.upper()      # env variables: <PREFIX>_BASE_URL, <PREFIX>_APP_NAME, ...

    config = target / "agent.yaml"
    text = config.read_text().replace("MY_AGENT", prefix).replace("my_agent", name)
    config.write_text(text.replace("input_field: question", f"input_field: {input_field}"))

    for case_file in (target / "testdata").rglob("*.json"):
        case = json.loads(case_file.read_text())
        case["input"] = {input_field: case["input"].pop("question")}
        case_file.write_text(json.dumps(case, indent=2) + "\n")

    env_lines = [f"{prefix}_BASE_URL=", f"{prefix}_APP_NAME={name}"]
    example = paths.ENV_DIR / ".env.example"
    if f"{prefix}_BASE_URL=" not in example.read_text():
        with example.open("a") as f:
            f.write(f"\n# --- {name} ---\n" + "\n".join(env_lines) + "\n")

    print(f"""Created agents/{name}/

Next:
  1. Add to env/.env (or env/.env.{name}):  {env_lines[0]}<agent url>
                                            {env_lines[1]}
  2. Fill in agents/{name}/agent.yaml (metrics, suites, headers)
  3. Add test cases to           agents/{name}/testdata/sanity/   (see TC_001.json)
  4. Try it:                     make run AGENT={name} SUITE=sanity
  5. Only if you need them:      fields.yaml (stage fields: make fields AGENT={name} to preview),
                                 checks: in agent.yaml, rubrics/ (own judges),
                                 client.py (agent is not Google ADK — see client.py.example),
                                 parser.py (logic YAML can't express — see parser.py.example)""")
