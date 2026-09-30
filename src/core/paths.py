"""
Where things live on disk. Every other module reads paths from here, so moving a folder is a
one-line change (and tests can point the whole framework at a temp folder by patching this module).

Always use them as `paths.AGENTS_DIR` (not `from src.core.paths import AGENTS_DIR`): the value is
then read at call time, which is what makes patching in tests work.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # the repository root (src/core/paths.py -> ../../)

AGENTS_DIR = ROOT / "agents"                    # one folder per agent: agent.yaml, testdata/, synth/, ...
OUTPUTS_DIR = ROOT / "outputs"                  # traces/ (latest trace per case) and runs/ (one folder per run)
BASELINES_DIR = ROOT / "baselines"              # baselines/<agent>/<suite>.json — committed, shared by the team
ENV_DIR = ROOT / "env"                          # env/.env and env/.env.<agent> — never committed
METRIC_LIBRARY = ROOT / "metric_library.yaml"   # built-in judge metrics and which engine runs each
