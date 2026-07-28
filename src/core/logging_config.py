"""One place to turn on logging the same way across every CLI entry point."""

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure a simple shared log format for CLI entry points."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
