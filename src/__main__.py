"""
Entry point for `python -m src ...` (what every `make` target runs). The commands live in cli.py.
"""

import sys

from src.cli import run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
