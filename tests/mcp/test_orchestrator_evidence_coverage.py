"""Tests for MCP orchestrator evidence coverage integration."""

from __future__ import annotations

from unittest.mock import patch

from mcp.config import MCPFetchParams
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.evidence_coverage import EvidenceCoverage
from mcp.orchestrator import MCPOrchestrator
from mcp.schemas.jira_models import McpTicketContext


@patch("mcp.orchestrator.mcp_enabled", return_value=False)
@patch("mcp.evidence_coverage.validate_all_connections", return_value=[])
def test_fetch_context_attaches_coverage_when_mcp_disabled(mock_validate, mock_enabled) -> None:
    context = MCPOrchestrator().fetch_context(MCPFetchParams(ticket_key="OPS-1"))

    assert context.evidence_coverage is not None
    assert isinstance(context.evidence_coverage, EvidenceCoverage)
    assert context.evidence_coverage.coverage_level == "low"


@patch("mcp.orchestrator.mcp_enabled", return_value=True)
@patch("mcp.orchestrator.registered_sources", return_value=["jira"])
@patch("mcp.orchestrator.resolve_runtime_connection", return_value=None)
@patch("mcp.orchestrator.get_provider_class")
@patch("mcp.evidence_coverage.validate_all_connections")
def test_fetch_context_attaches_coverage_after_provider_fetch(
    mock_validate,
    mock_get_provider_class,
    mock_resolve,
    mock_sources,
    mock_enabled,
) -> None:
    provider = mock_get_provider_class.return_value.return_value
    provider.is_enabled.return_value = True
    provider.fetch.return_value = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-9", summary="Issue"),
    )
    mock_validate.return_value = []

    context = MCPOrchestrator().fetch_context(
        MCPFetchParams(ticket_key="OPS-9", enabled_sources=["jira"])
    )

    assert context.evidence_coverage is not None
    assert "jira" in context.evidence_coverage.available_sources
    provider.fetch.assert_called_once()
