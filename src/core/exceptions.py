"""
The framework's own errors. The CLI prints these as one clean "ERROR: ..." line instead of a
traceback, so their messages must say what to fix and where.
"""


class ConfigError(Exception):
    """A config file (agent.yaml, metric_library.yaml, synth.yaml) or a test case is wrong or incomplete."""


class JudgeConfigError(ConfigError):
    """A CORTEX / Pegasus setting is missing from env/.env."""


class AgentCallError(Exception):
    """The agent could not be reached or returned something unusable."""
