"""Tests for deterministic JIRA normalization and hint extraction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib import error as urlerror

import pytest

from api.services.jira_service import (
    JiraConfigError,
    JiraExternalApiError,
    _build_search_jql_from_q,
    _extract_hints,
    _fetch_issue_from_jira,
    _flatten_rich_text,
    _jira_config,
    _jira_config_from_env,
    _looks_like_ticket_key,
    _normalize_ticket_key,
    fetch_ticket_context,
)
from mcp.runtime_connection import ProviderRuntimeConnection


def test_normalize_ticket_key_uppercases_and_validates() -> None:
    assert _normalize_ticket_key("abc-123") == "ABC-123"


def test_looks_like_ticket_key() -> None:
    assert _looks_like_ticket_key("LAAA-83")
    assert _looks_like_ticket_key("laaa-83")
    assert not _looks_like_ticket_key("auth failure")


def test_build_search_jql_from_q_text_search() -> None:
    jql, mode = _build_search_jql_from_q("auth failure")
    assert mode == "text"
    assert 'text ~ "auth failure"' in jql
    assert "ORDER BY updated DESC" in jql


def test_build_search_jql_from_q_issuekey() -> None:
    jql, mode = _build_search_jql_from_q("LAAA-83")
    assert mode == "issuekey"
    assert jql == "issuekey = LAAA-83"


@patch("api.services.jira_service._fetch_issue_from_jira")
@patch("mcp.integration_resolver.resolve_runtime_connection_for_workspace")
def test_fetch_ticket_context_workspace_uses_runtime_resolver(
    mock_resolve: object,
    mock_fetch: object,
) -> None:
    mock_resolve.return_value = ProviderRuntimeConnection(
        connection_id="conn-elm-1",
        workspace_id="ELM",
        provider="jira",
        base_url="https://elm.atlassian.net",
        credentials={"email": "dev@elm.com", "api_token": "secret-token"},
    )
    mock_fetch.return_value = {
        "id": "10083",
        "key": "LAAA-83",
        "fields": {
            "summary": "Auth regression",
            "description": "desc",
            "comment": {"comments": []},
            "status": {"name": "Open"},
            "priority": {"name": "High"},
            "labels": ["backend"],
            "created": "2026-01-01T00:00:00.000+0000",
            "updated": "2026-01-02T00:00:00.000+0000",
        },
    }
    out = fetch_ticket_context("LAAA-83", workspace_id="ELM")
    mock_resolve.assert_called_once_with("ELM", "jira")
    mock_fetch.assert_called_once_with(
        {
            "base_url": "https://elm.atlassian.net",
            "email": "dev@elm.com",
            "api_token": "secret-token",
        },
        "LAAA-83",
    )
    assert out.ticket.ticket_key == "LAAA-83"


@patch("api.services.jira_service._fetch_issue_from_jira")
@patch("api.services.jira_service._jira_config_from_env")
def test_fetch_ticket_context_uses_direct_issue_lookup(mock_cfg: object, mock_fetch: object) -> None:
    mock_cfg.return_value = {
        "base_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": "token",
    }
    mock_fetch.return_value = {
        "id": "10083",
        "key": "LAAA-83",
        "fields": {
            "summary": "Auth regression",
            "description": "desc",
            "comment": {"comments": []},
            "status": {"name": "Open"},
            "priority": {"name": "High"},
            "labels": ["backend"],
            "created": "2026-01-01T00:00:00.000+0000",
            "updated": "2026-01-02T00:00:00.000+0000",
        },
    }
    out = fetch_ticket_context("LAAA-83")
    mock_fetch.assert_called_once_with(mock_cfg.return_value, "LAAA-83")
    assert out.ticket.ticket_key == "LAAA-83"
    assert out.ticket.summary == "Auth regression"
    assert out.ticket.status == "Open"
    assert out.ticket.labels == ["backend"]


def test_fetch_issue_from_jira_calls_direct_issue_endpoint() -> None:
    cfg = {"base_url": "https://example.atlassian.net", "email": "dev@example.com", "api_token": "token"}
    issue_payload = {
        "id": "10083",
        "key": "LAAA-83",
        "fields": {
            "summary": "Auth regression",
            "description": "",
            "comment": {"comments": []},
            "status": {"name": "Open"},
            "priority": {"name": "High"},
            "labels": ["backend"],
            "created": "2026-01-01T00:00:00.000+0000",
            "updated": "2026-01-02T00:00:00.000+0000",
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(issue_payload).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("api.services.jira_service.request.urlopen", return_value=mock_resp) as mock_urlopen:
        out = _fetch_issue_from_jira(cfg, "LAAA-83")
    assert out["key"] == "LAAA-83"
    req = mock_urlopen.call_args[0][0]
    assert req.full_url.startswith("https://example.atlassian.net/rest/api/3/issue/LAAA-83")


def test_flatten_rich_text_handles_adf() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "PaymentService timeout"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "in /srv/api/app.py"},
                ],
            }
        ],
    }
    out = _flatten_rich_text(adf)
    assert "PaymentService timeout" in out
    assert "/srv/api/app.py" in out


def test_extract_hints_from_clean_text() -> None:
    text = (
        "prod outage in paymentservice. "
        "Exception thrown at /srv/payment/handler.py and C:\\apps\\svc\\main.py. "
        "HTTP 503 observed."
    )
    hints = _extract_hints(text, labels=["sev1", "payments"])
    assert "paymentservice" in hints.service_names
    assert "prod" in hints.environment_names
    assert "/srv/payment/handler.py" in hints.file_paths
    assert any(path.startswith("C:\\apps\\svc\\") for path in hints.file_paths)
    assert "exception" in hints.error_keywords
    assert "503" in hints.error_keywords
    assert hints.labels == ["sev1", "payments"]


def test_jira_config_rejects_invalid_base_url() -> None:
    with (
        patch.dict(
            "os.environ",
            {"JIRA_BASE_URL": "not-a-url", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "token"},
            clear=False,
        ),
        pytest.raises(JiraConfigError),
    ):
        _jira_config_from_env()


def test_jira_config_rejects_invalid_email() -> None:
    with (
        patch.dict(
            "os.environ",
            {"JIRA_BASE_URL": "https://example.atlassian.net", "JIRA_EMAIL": "invalid", "JIRA_API_TOKEN": "token"},
            clear=False,
        ),
        pytest.raises(JiraConfigError),
    ):
        _jira_config_from_env()


@patch("mcp.integration_resolver.resolve_runtime_connection_for_workspace")
def test_jira_config_workspace_uses_runtime_resolver(mock_resolve: object) -> None:
    mock_resolve.return_value = ProviderRuntimeConnection(
        connection_id="conn-elm-1",
        workspace_id="ELM",
        provider="jira",
        base_url="https://elm.atlassian.net",
        credentials={"email": "dev@elm.com", "api_token": "secret-token"},
    )
    cfg = _jira_config(workspace_id="ELM")
    assert cfg == {
        "base_url": "https://elm.atlassian.net",
        "email": "dev@elm.com",
        "api_token": "secret-token",
    }
    mock_resolve.assert_called_once_with("ELM", "jira")


@patch("mcp.integration_resolver.resolve_runtime_connection_for_workspace", return_value=None)
def test_jira_config_workspace_no_connection_raises(_mock_resolve: object) -> None:
    with (
        patch.dict(
            "os.environ",
            {
                "JIRA_BASE_URL": "https://fallback.atlassian.net",
                "JIRA_EMAIL": "fallback@example.com",
                "JIRA_API_TOKEN": "fallback-token",
            },
            clear=False,
        ),
        pytest.raises(JiraConfigError, match="no enabled Jira integration connection"),
    ):
        _jira_config(workspace_id="ELM")


@patch("mcp.integration_resolver.resolve_runtime_connection_for_workspace")
def test_jira_config_workspace_missing_credentials_raises(mock_resolve: object) -> None:
    mock_resolve.return_value = ProviderRuntimeConnection(
        connection_id="conn-elm-1",
        workspace_id="ELM",
        provider="jira",
        base_url="https://elm.atlassian.net",
        credentials={"email": "dev@elm.com"},
    )
    with pytest.raises(JiraConfigError, match="missing credentials"):
        _jira_config(workspace_id="ELM")


@patch("api.services.jira_service._jira_config_from_env")
def test_jira_config_without_workspace_uses_env(mock_env_cfg: object) -> None:
    mock_env_cfg.return_value = {
        "base_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": "token",
    }
    cfg = _jira_config(workspace_id=None)
    assert cfg == mock_env_cfg.return_value
    mock_env_cfg.assert_called_once()


def test_fetch_issue_retries_then_raises_sanitized_error() -> None:
    cfg = {"base_url": "https://example.atlassian.net", "email": "dev@example.com", "api_token": "token"}
    with (
        patch("api.services.jira_service.request.urlopen", side_effect=urlerror.URLError("down")),
        patch.dict("os.environ", {"JIRA_TIMEOUT_SEC": "5", "JIRA_MAX_RETRIES": "1"}, clear=False),
        pytest.raises(JiraExternalApiError) as exc,
    ):
        _fetch_issue_from_jira(cfg, "PROJ-1")
    assert "network failure" in str(exc.value)
