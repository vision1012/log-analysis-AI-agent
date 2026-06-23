"""Tests for Confluence MCP provider with mocked API responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.confluence_provider import ConfluenceProvider


@pytest.fixture
def confluence_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("CONFLUENCE_MCP_ENABLED", "true")
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "cf-token")
    monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "OPS")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _urlopen_side_effect():
    def _side_effect(req, timeout=15):
        url = req.full_url
        if "/user/current" in url:
            return _mock_response({"type": "known", "accountId": "abc123"})
        if "/content/search" in url:
            return _mock_response(
                {
                    "results": [
                        {
                            "id": "1001",
                            "type": "page",
                            "title": "auth-service Runbook",
                            "excerpt": "Rollback and restart procedures for auth-service",
                            "space": {"key": "OPS"},
                            "_links": {
                                "webui": "/wiki/spaces/OPS/pages/1001",
                                "base": "https://acme.atlassian.net",
                            },
                            "metadata": {"labels": {"results": [{"name": "runbook"}]}},
                        },
                        {
                            "id": "1002",
                            "type": "page",
                            "title": "Known issue: OOM on auth-service",
                            "excerpt": "Workaround: increase memory limits",
                            "space": {"key": "OPS"},
                            "_links": {
                                "webui": "/wiki/spaces/OPS/pages/1002",
                                "base": "https://acme.atlassian.net",
                            },
                            "metadata": {"labels": {"results": [{"name": "known-issue"}]}},
                        },
                        {
                            "id": "1003",
                            "type": "page",
                            "title": "auth-service Architecture",
                            "excerpt": "AuthService API and TokenCache components",
                            "space": {"key": "OPS"},
                            "_links": {
                                "webui": "/wiki/spaces/OPS/pages/1003",
                                "base": "https://acme.atlassian.net",
                            },
                            "metadata": {"labels": {"results": [{"name": "architecture"}]}},
                        },
                    ]
                }
            )
        if "/content/1001" in url:
            return _mock_response(
                {
                    "id": "1001",
                    "title": "auth-service Runbook",
                    "version": {"when": "2024-01-01T10:00:00.000Z"},
                    "body": {"storage": {"value": "<p>Rollback auth-service deployment steps.</p>"}},
                    "space": {"key": "OPS"},
                    "metadata": {"labels": {"results": [{"name": "runbook"}]}},
                }
            )
        if "/content/1002" in url:
            return _mock_response(
                {
                    "id": "1002",
                    "title": "Known issue: OOM on auth-service",
                    "version": {"when": "2024-01-02T10:00:00.000Z"},
                    "body": {
                        "storage": {
                            "value": "<p>Workaround: increase memory limits when OOM error occurs.</p>"
                        }
                    },
                    "space": {"key": "OPS"},
                    "metadata": {"labels": {"results": [{"name": "known-issue"}, {"name": "critical"}]}},
                }
            )
        if "/content/1003" in url:
            return _mock_response(
                {
                    "id": "1003",
                    "title": "auth-service Architecture",
                    "version": {"when": "2024-01-03T10:00:00.000Z"},
                    "body": {
                        "storage": {
                            "value": "<p>AuthService talks to TokenCache and UserDB.</p>"
                        }
                    },
                    "space": {"key": "OPS"},
                    "metadata": {"labels": {"results": [{"name": "architecture"}]}},
                }
            )
        return _mock_response({})

    return _side_effect


@patch("mcp.providers.confluence_provider.request.urlopen")
def test_confluence_provider_fetch_normalizes_documents(mock_urlopen, confluence_env):
    mock_urlopen.side_effect = _urlopen_side_effect()

    provider = ConfluenceProvider()
    assert provider.is_enabled() is True
    assert provider.is_configured() is True

    ctx = provider.fetch(
        MCPFetchParams(
            ticket_key="OPS-20",
            service_name="auth-service",
        )
    )
    assert len(ctx.runbook_documents) == 1
    runbook = ctx.runbook_documents[0]
    assert runbook.document_id == "1001"
    assert runbook.service_name == "auth-service"
    assert "runbook" in runbook.labels

    assert len(ctx.known_issue_documents) == 1
    known = ctx.known_issue_documents[0]
    assert known.document_id == "1002"
    assert known.affected_service == "auth-service"
    assert "oom" in known.error_keywords
    assert known.severity == "critical"

    assert len(ctx.architecture_documents) == 1
    arch = ctx.architecture_documents[0]
    assert arch.document_id == "1003"
    assert "AuthService" in arch.components

    assert ctx.source_metadata[0].source == "confluence"


@patch("mcp.providers.confluence_provider.request.urlopen")
def test_confluence_provider_health_check_ok(mock_urlopen, confluence_env):
    mock_urlopen.return_value = _mock_response({"type": "known", "accountId": "abc123"})
    health = ConfluenceProvider().health_check()
    assert health.source == "confluence"
    assert health.enabled is True
    assert health.configured is True
    assert health.reachable is True


def test_confluence_provider_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("CONFLUENCE_MCP_ENABLED", "false")
    provider = ConfluenceProvider()
    assert provider.is_enabled() is False


def test_confluence_provider_not_configured_without_credentials(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("CONFLUENCE_MCP_ENABLED", "true")
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    provider = ConfluenceProvider()
    assert provider.is_configured() is False
    assert provider.fetch(MCPFetchParams(ticket_key="OPS-1")).runbook_documents == []
