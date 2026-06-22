"""MCP layer: fetch normalized external investigation context (JIRA, GitHub, GitLab)."""

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.orchestrator import MCPOrchestrator

__all__ = ["MCPOrchestrator", "UnifiedInvestigationContext"]
