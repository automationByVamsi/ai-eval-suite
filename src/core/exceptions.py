"""All framework-specific errors. Keep this list flat and small."""


class FrameworkError(Exception):
    """Base class for every error raised by this framework."""


class ConfigError(FrameworkError):
    """A YAML config file is missing, malformed, or missing a required key."""


class AgentNotFoundError(FrameworkError):
    """Requested agent name is not defined in agents.yaml."""


class MetricNotFoundError(FrameworkError):
    """Requested metric type is not registered (YAML `type:` has no matching class)."""


class TraceParseError(FrameworkError):
    """A captured raw trace file could not be parsed into the expected shape."""


class CortexClientError(FrameworkError):
    """The CORTEX LLM gateway call failed (network, auth, or bad response)."""


class AgentInvocationError(FrameworkError):
    """A live agent call (e.g. the ADK adapter) failed (network or bad response)."""
