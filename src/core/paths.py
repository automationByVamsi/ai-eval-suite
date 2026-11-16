"""Where things live on disk.

Use as `paths.AGENTS_DIR` (not `from ... import`) so tests can patch this module.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

AGENTS_DIR = ROOT / "agents"
OUTPUTS_DIR = ROOT / "outputs"                  # traces/ and runs/
BASELINES_DIR = ROOT / "baselines"              # committed, shared by the team
ENV_DIR = ROOT / "env"                          # never committed
METRIC_LIBRARY = ROOT / "metric_library.yaml"
