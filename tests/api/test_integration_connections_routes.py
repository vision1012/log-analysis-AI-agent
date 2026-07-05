"""API route tests for integration connections."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from integrations.connection_models import (
    IntegrationConnectionSummary,
    IntegrationConnectionView,
    IntegrationCredentialsMeta,
    IntegrationValidationResult,
)

client = TestClient(app)


def _connection_view() -> IntegrationConnectionView:
    return IntegrationConnectionView(
        id="conn-1",
        workspace_id="00000000-0000-0000-0000-000000000001",
        provider="github",
        display_name="GitHub Prod",
        org_name="acme",
        repo_name="payments",
        is_enabled=True,
        created_by="00000000-0000-0000-0000-000000000001",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
        credentials=IntegrationCredentialsMeta(configured=True, secret_fields=["token"]),
    )


def _connection_summary(*, healthy: bool = True) -> IntegrationConnectionSummary:
    return IntegrationConnectionSummary(
        connection_id="conn-1",
        workspace_id="00000000-0000-0000-0000-000000000001",
        provider="github",
        display_name="GitHub Prod",
        is_enabled=True,
        healthy=healthy,
    )


@patch("api.routes.integration_connections.connection_service.create_connection")
def test_create_integration_connection_masks_secrets(mock_create) -> None:
    mock_create.return_value = _connection_view()
    response = client.post(
        "/api/v1/integrations/connections",
        json={
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "provider": "github",
            "display_name": "GitHub Prod",
            "org_name": "acme",
            "repo_name": "payments",
            "credentials": {"token": "ghp_super_secret"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "github"
    assert body["credentials"]["configured"] is True
    assert body["credentials"]["secret_fields"] == ["token"]
    assert "ghp_super_secret" not in response.text


@patch("api.routes.integration_connections.connection_service.list_connection_summaries")
def test_list_integration_connections_returns_summary_array(mock_list) -> None:
    mock_list.return_value = [_connection_summary()]
    response = client.get("/api/v1/integrations/connections")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["connection_id"] == "conn-1"
    assert body[0]["healthy"] is True
    assert body[0]["provider"] == "github"


@patch("api.routes.integration_connections.connection_service.list_connection_summaries")
def test_list_integration_connections_accepts_workspace_id(mock_list) -> None:
    mock_list.return_value = [_connection_summary()]
    response = client.get(
        "/api/v1/integrations/connections",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert response.status_code == 200
    mock_list.assert_called_once()


@patch("api.routes.integration_connections.connection_service.update_connection")
def test_put_integration_connection(mock_update) -> None:
    mock_update.return_value = _connection_view()
    response = client.put(
        "/api/v1/integrations/connections/conn-1",
        json={"display_name": "Updated"},
    )
    assert response.status_code == 200
    mock_update.assert_called_once()


@patch("api.routes.integration_connections.connection_service.validate_connection")
def test_validate_integration_connection(mock_validate) -> None:
    mock_validate.return_value = IntegrationValidationResult(
        connection_id="conn-1",
        provider="jira",
        status="healthy",
        detail="ok",
        validated_at=datetime(2024, 1, 2),
    )
    response = client.post("/api/v1/integrations/connections/conn-1/validate")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@patch("api.routes.integration_connections.connection_service.delete_connection")
def test_delete_integration_connection(mock_delete) -> None:
    response = client.delete("/api/v1/integrations/connections/conn-1")
    assert response.status_code == 204
    mock_delete.assert_called_once()


def test_integrations_routes_registered_in_openapi() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/integrations/connections" in paths
    assert "get" in paths["/api/v1/integrations/connections"]
    assert "post" in paths["/api/v1/integrations/connections"]
    detail = paths["/api/v1/integrations/connections/{connection_id}"]
    assert "put" in detail
    assert "delete" in detail
    assert "post" in paths["/api/v1/integrations/connections/{connection_id}/validate"]
