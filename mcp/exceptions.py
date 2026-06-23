"""MCP provider and orchestration errors."""


class MCPError(Exception):
    """Base MCP error."""


class MCPConfigError(MCPError):
    """Missing or invalid MCP configuration."""


class MCPProviderError(MCPError):
    """A single provider failed during fetch."""


class MCPProviderUnavailableError(MCPProviderError):
    """Provider is disabled or not registered."""
