"""Tests for MCP integration connection resolver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp.config import MCPFetchParams
from mcp.integration_resolver import resolve_runtime_connection
from mcp.runtime_connection import ProviderRuntimeConnection


@patch("mcp.integration_resolver.get_db_session_readonly")
@patch("mcp.integration_resolver.get_enabled_connection")
@patch("mcp.integration_resolver.decrypt_credentials")
def test_resolve_runtime_connection_returns_provider_runtime(
    mock_decrypt,
    mock_get_enabled,
    mock_session_ctx,
) -> None:
    row = MagicMock()
    row.id = "conn-jira-1"
    row.workspace_id = "team-a"
    row.provider = "jira"
    row.base_url = "https://acme.atlassian.net"
    row.org_name = None
    row.project_key = "OPS"
    row.repo_name = None
    row.config_json = {}
    row.encrypted_credentials = "enc"
    row.is_enabled = True
    mock_get_enabled.return_value = row
    mock_decrypt.return_value = {"email": "bot@example.com", "api_token": "secret"}
    mock_session_ctx.return_value.__enter__.return_value = MagicMock()

    runtime = resolve_runtime_connection(
        MCPFetchParams(ticket_key="OPS-1", workspace_id="team-a"),
        "jira",
    )

    assert runtime is not None
    assert isinstance(runtime, ProviderRuntimeConnection)
    assert runtime.connection_id == "conn-jira-1"
    assert runtime.credentials["api_token"] == "secret"
    assert runtime.project_key == "OPS"


def test_resolve_runtime_connection_without_workspace_returns_none() -> None:
    runtime = resolve_runtime_connection(MCPFetchParams(ticket_key="OPS-1"), "jira")
    assert runtime is None
