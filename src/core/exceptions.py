"""The framework's own errors; the CLI prints them as one "ERROR: ..." line, so messages must say what to fix."""


class ConfigError(Exception):
    """A config file or test case is wrong or incomplete."""


class JudgeConfigError(ConfigError):
    """A CORTEX / Pegasus setting is missing from env/.env."""


class AgentCallError(Exception):
    """The agent could not be reached or returned something unusable."""
