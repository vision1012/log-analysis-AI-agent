"""Tests for centralized MCP connection manager."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp.connection_manager import (
    clear_connection_cache,
    validate_all_connections,
    validate_provider,
)
from mcp.schemas.common import ProviderHealth


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_connection_cache()
    yield
    clear_connection_cache()


def _health(
    source: str,
    *,
    enabled: bool = True,
    configured: bool = True,
    reachable: bool = True,
    detail: str = "ok",
) -> ProviderHealth:
    return ProviderHealth(
        source=source,  # type: ignore[arg-type]
        enabled=enabled,
        configured=configured,
        reachable=reachable,
        detail=detail,
    )


@patch("mcp.connection_manager.get_provider_class")
def test_validate_provider_returns_connection_status(mock_get_provider_class) -> None:
    provider = MagicMock()
    provider.health_check.return_value = _health("github")
    mock_get_provider_class.return_value = MagicMock(return_value=provider)

    status = validate_provider("GitHub")

    assert status.provider == "github"
    assert status.configured is True
    assert status.healthy is True
    assert status.error_message is None
    assert status.last_checked
    provider.health_check.assert_called_once()


@patch("mcp.connection_manager.get_provider_class")
def test_validate_provider_surfaces_configuration_error(mock_get_provider_class) -> None:
    provider = MagicMock()
    provider.health_check.return_value = _health(
        "datadog",
        configured=False,
        reachable=False,
        detail="missing DATADOG_API_KEY",
    )
    mock_get_provider_class.return_value = MagicMock(return_value=provider)

    status = validate_provider("datadog")

    assert status.configured is False
    assert status.healthy is False
    assert status.error_message == "missing DATADOG_API_KEY"


@patch("mcp.connection_manager.get_provider_class")
def test_validate_provider_unknown_name_raises(mock_get_provider_class) -> None:
    with pytest.raises(KeyError, match="unknown MCP provider"):
        validate_provider("unknown")


@patch("mcp.connection_manager.get_provider_class")
def test_validate_all_connections_without_workspace_uses_env_providers(
    mock_get_provider_class,
) -> None:
    def _provider_for(source: str):
        provider = MagicMock()
        provider.health_check.return_value = _health(source)
        return MagicMock(return_value=provider)

    mock_get_provider_class.side_effect = _provider_for

    statuses = validate_all_connections()

    assert len(statuses) == 8
    assert {status.provider for status in statuses} == {
        "jira",
        "github",
        "gitlab",
        "jenkins",
        "datadog",
        "kubernetes",
        "pagerduty",
        "confluence",
    }


@patch("mcp.connection_manager._validate_runtime")
@patch("mcp.connection_manager.runtime_connection_from_row")
@patch("mcp.connection_manager._list_enabled_workspace_connections")
def test_validate_all_connections_with_workspace_uses_db_rows(
    mock_list_rows,
    mock_runtime_from_row,
    mock_validate_runtime,
) -> None:
    row_jira = MagicMock()
    row_jira.id = "conn-jira"
    row_jira.provider = "jira"
    row_jira.display_name = "Jira Prod"
    row_jira.is_enabled = True

    row_github = MagicMock()
    row_github.id = "conn-github"
    row_github.provider = "github"
    row_github.display_name = "GitHub Prod"
    row_github.is_enabled = True

    mock_list_rows.return_value = [row_jira, row_github]
    mock_runtime_from_row.return_value = MagicMock()
    mock_validate_runtime.side_effect = [
        MagicMock(provider="jira", configured=True, healthy=True, last_checked="t1"),
        MagicMock(provider="github", configured=True, healthy=True, last_checked="t2"),
    ]

    statuses = validate_all_connections(workspace_id="ws-1", force_refresh=True)

    assert len(statuses) == 2
    mock_list_rows.assert_called_once_with("ws-1")
    assert mock_validate_runtime.call_count == 2


@patch("mcp.connection_manager.resolve_runtime_connection_for_workspace")
def test_validate_provider_with_workspace_missing_connection(mock_resolve) -> None:
    mock_resolve.return_value = None

    status = validate_provider("jira", workspace_id="ws-1")

    assert status.provider == "jira"
    assert status.configured is False
    assert status.healthy is False
    assert status.error_message == "no integration connection configured"


@patch("mcp.connection_manager.get_provider_class")
def test_validate_provider_uses_cache(mock_get_provider_class, monkeypatch) -> None:
    monkeypatch.setenv("MCP_HEALTH_CACHE_SECONDS", "300")
    provider = MagicMock()
    provider.health_check.return_value = _health("jira")
    mock_get_provider_class.return_value = MagicMock(return_value=provider)

    first = validate_provider("jira")
    second = validate_provider("jira")

    assert first.provider == second.provider
    assert provider.health_check.call_count == 1


@patch("mcp.connection_manager.get_provider_class")
def test_validate_provider_force_refresh_bypasses_cache(mock_get_provider_class, monkeypatch) -> None:
    monkeypatch.setenv("MCP_HEALTH_CACHE_SECONDS", "300")
    provider = MagicMock()
    provider.health_check.return_value = _health("jira")
    mock_get_provider_class.return_value = MagicMock(return_value=provider)

    validate_provider("jira")
    validate_provider("jira", force_refresh=True)

    assert provider.health_check.call_count == 2


@patch("mcp.connection_manager.get_provider_class")
def test_validate_all_connections_force_refresh_bypasses_cache(mock_get_provider_class, monkeypatch) -> None:
    monkeypatch.setenv("MCP_HEALTH_CACHE_SECONDS", "300")

    def _provider_for(source: str):
        provider = MagicMock()
        provider.health_check.return_value = _health(source)
        return MagicMock(return_value=provider)

    mock_get_provider_class.side_effect = _provider_for

    validate_all_connections()
    validate_all_connections(force_refresh=True)

    assert mock_get_provider_class.call_count == 16
