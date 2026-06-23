"""Base MCP provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mcp.config import MCPFetchParams
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import ProviderHealth


class BaseMCPProvider(ABC):
    """Fetch normalized investigation slices from one external source."""

    source: str

    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether this provider is enabled via environment flags."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether required credentials/settings are present."""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Probe provider reachability without full fetch."""

    @abstractmethod
    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        """Return a partial unified context from this provider only."""
