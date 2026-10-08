import json
from pathlib import Path

from src.core.agent_config import load_agent
from src.fields.extract import extract


def test_print_fields():
    trace = json.loads(Path("outputs/traces/knowledge_agent/sanity/TC_002.json").read_text())
    values, _ = extract(trace, load_agent("knowledge_agent").fields, offline=True)
    for name, value in values.items():
        print(f"{name:<25} = {value}")
