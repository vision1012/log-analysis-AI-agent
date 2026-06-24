"""Tests for MCP orchestrator workspace runtime connection wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp.config import MCPFetchParams
from mcp.orchestrator import MCPOrchestrator
from mcp.runtime_connection import ProviderRuntimeConnection


@patch("mcp.orchestrator.mcp_enabled", return_value=True)
@patch("mcp.orchestrator.registered_sources", return_value=["jira", "github"])
@patch("mcp.orchestrator.resolve_runtime_connection")
@patch("mcp.orchestrator.get_provider_class")
@patch("mcp.orchestrator.attach_evidence_coverage", side_effect=lambda ctx, **_: ctx)
def test_orchestrator_passes_runtime_connection_to_providers(
    mock_attach,
    mock_get_provider_class,
    mock_resolve,
    mock_sources,
    mock_enabled,
) -> None:
    runtime = ProviderRuntimeConnection(
        connection_id="conn-1",
        workspace_id="team-a",
        provider="jira",
        base_url="https://jira.example.net",
        credentials={"email": "a@b.com", "api_token": "x"},
    )
    mock_resolve.side_effect = lambda params, source: runtime if source == "jira" else None

    provider_instance = MagicMock()
    provider_instance.is_enabled.return_value = True
    provider_instance.fetch.return_value = MagicMock()
    mock_get_provider_class.return_value = MagicMock(return_value=provider_instance)

    MCPOrchestrator().fetch_context(
        MCPFetchParams(ticket_key="OPS-1", workspace_id="team-a", enabled_sources=["jira", "github"])
    )

    assert mock_get_provider_class.return_value.call_count == 2
    first_call = mock_get_provider_class.return_value.call_args_list[0]
    assert first_call.kwargs["runtime_connection"] == runtime
    mock_attach.assert_called_once()
    assert mock_attach.call_args.kwargs.get("workspace_id") == "team-a"
