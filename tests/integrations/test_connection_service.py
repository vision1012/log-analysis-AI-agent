"""Tests for integration connection service validation and workspace access."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from integrations.connection_models import IntegrationConnectionCreate, IntegrationConnectionSecretPayload
from integrations.connection_service import (
    IntegrationValidationError,
    assert_workspace_access,
    validate_provider_credentials,
)
from schemas.users import UserResponse


def _user(*, team: str | None = "team-a") -> UserResponse:
    return UserResponse(
        user_id="00000000-0000-0000-0000-000000000001",
        first_name="Test",
        last_name="User",
        email="test@example.com",
        is_email_verified=True,
        role="developer",
        team=team,
        created_at=datetime(2020, 1, 1),
    )


def test_assert_workspace_access_allows_team_workspace() -> None:
    assert_workspace_access(_user(team="team-a"), "team-a")


def test_assert_workspace_access_allows_personal_workspace() -> None:
    user = _user(team=None)
    assert_workspace_access(user, user.user_id)


def test_assert_workspace_access_denies_foreign_workspace() -> None:
    with pytest.raises(HTTPException) as exc:
        assert_workspace_access(_user(team="team-a"), "team-b")
    assert exc.value.status_code == 403


@patch("integrations.connection_service._http_get_json")
def test_validate_jira_credentials_success(mock_http) -> None:
    mock_http.return_value = {"accountId": "abc"}
    validate_provider_credentials(
        provider="jira",
        base_url="https://example.atlassian.net",
        org_name=None,
        repo_name=None,
        credentials={"email": "user@example.com", "api_token": "token"},
    )
    called_url = mock_http.call_args.args[0]
    assert "/rest/api/3/myself" in called_url


@patch("integrations.connection_service._http_get_json")
def test_validate_github_credentials_checks_repo_when_configured(mock_http) -> None:
    mock_http.return_value = {"login": "octo"}
    validate_provider_credentials(
        provider="github",
        base_url=None,
        org_name="acme",
        repo_name="payments",
        credentials={"token": "ghp_test"},
    )
    assert mock_http.call_count == 2


def test_validate_github_credentials_requires_token() -> None:
    with pytest.raises(IntegrationValidationError):
        validate_provider_credentials(
            provider="github",
            base_url=None,
            org_name=None,
            repo_name=None,
            credentials={},
        )


@patch("integrations.connection_service.encrypt_credentials", return_value="enc")
@patch("integrations.connection_service.get_db_session")
def test_create_connection_encrypts_credentials(mock_session_ctx, mock_encrypt, monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    session = MagicMock()
    mock_session_ctx.return_value.__enter__.return_value = session

    row = MagicMock()
    row.id = "conn-1"
    row.workspace_id = "team-a"
    row.provider = "jira"
    row.display_name = "Jira Prod"
    row.base_url = "https://example.atlassian.net"
    row.org_name = None
    row.project_key = None
    row.repo_name = None
    row.config_json = {}
    row.is_enabled = True
    row.created_by = "00000000-0000-0000-0000-000000000001"
    row.created_at = datetime(2024, 1, 1)
    row.updated_at = datetime(2024, 1, 1)
    row.last_validated_at = None
    row.last_validation_status = None
    row.last_validation_error = None

    with patch("integrations.connection_service.repo_create_connection", return_value=row):
        from integrations import connection_service

        view = connection_service.create_connection(
            _user(team="team-a"),
            IntegrationConnectionCreate(
                workspace_id="team-a",
                provider="jira",
                display_name="Jira Prod",
                base_url="https://example.atlassian.net",
                credentials=IntegrationConnectionSecretPayload(
                    email="user@example.com",
                    api_token="secret",
                ),
            ),
        )

    mock_encrypt.assert_called_once()
    assert view.id == "conn-1"
    assert view.credentials.configured is True
    assert "api_token" in view.credentials.secret_fields
    assert '"api_token": "secret"' not in view.model_dump_json()
